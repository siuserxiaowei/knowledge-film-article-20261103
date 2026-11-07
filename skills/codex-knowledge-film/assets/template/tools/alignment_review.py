"""Offline, fail-closed review of imported narration and reproducible PCM cuts.

ASR is evidence, not an automatic human review. ``candidate`` preserves raw ASR
and writes pending status. No network, ASR model, or topic-specific aliases are
included. Reviewers explicitly record their listening/independent-ASR method.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from difflib import SequenceMatcher
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unicodedata
import wave

SR = 48000
CONTEXT_KEYS = ("sourceFile", "sourceSha256", "startSeconds", "endSeconds")


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def project_file(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Review/audio paths must be project-relative")
    root = Path(root).resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Review/audio path is missing or leaves project: " + value)
    return path


def normalize(text):
    if not isinstance(text, str):
        raise ValueError("ASR/script text must be a string")
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def normalized_asr(raw, replacements=()):
    result = normalize(raw)
    original = result
    changed_characters = 0
    for replacement in replacements:
        if not isinstance(replacement, dict) or replacement.get("kind") != "homophone":
            raise ValueError("ASR normalization requires kind=homophone")
        before, after = normalize(replacement.get("from")), normalize(replacement.get("to"))
        if not before or len(before) != len(after) or before == after or len(before) > 4 or len(before) >= len(original):
            raise ValueError("Homophone normalization must be a nonempty equal-length substitution")
        if not isinstance(replacement.get("reason"), str) or not replacement["reason"].strip():
            raise ValueError("Homophone normalization needs listening/independent-ASR evidence in reason")
        if before not in result:
            raise ValueError("Normalization input is absent from raw ASR")
        changed_characters += result.count(before) * len(before)
        if changed_characters > max(1, len(original) // 3):
            raise ValueError("Normalization changes too much ASR; preserve the discrepancy and obtain independent evidence")
        result = result.replace(before, after)
    return result


def transcript_diffs(expected, raw_asr, normalizations=()):
    """Compare the entire normalized text; similarity never determines success."""
    expected = normalize(expected)
    actual = normalized_asr(raw_asr, normalizations)
    missing, extra, changes = [], [], []
    for tag, a, b, c, d in SequenceMatcher(None, expected, actual, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        direction = "start" if a == 0 else "end" if b == len(expected) else "middle"
        change = {"operation": tag, "direction": direction,
                  "expected": expected[a:b], "actual": actual[c:d]}
        changes.append(change)
        if a != b:
            missing.append({"text": expected[a:b], "direction": direction})
        if c != d:
            extra.append({"text": actual[c:d], "direction": direction})
    prefix = 0
    for left, right in zip(expected, actual):
        if left != right:
            break
        prefix += 1
    suffix = 0
    for left, right in zip(reversed(expected), reversed(actual)):
        if left != right:
            break
        suffix += 1
    return {"status": "pass" if expected and expected == actual else "fail",
            "expectedNormalized": expected, "asrNormalized": actual,
            "prefixMatchedCharacters": prefix, "suffixMatchedCharacters": suffix,
            "missing": missing, "extra": extra, "changes": changes,
            "similarityForDiagnosisOnly": SequenceMatcher(None, expected, actual, autojunk=False).ratio()}


def analyze_rows(rows):
    checks = []
    for row in rows:
        check = transcript_diffs(row["text"], row["rawAsr"], row.get("normalizations", []))
        checks.append({"id": row["id"], **check})
    crossings = []
    for left, right in zip(checks, checks[1:]):
        for missing in left["missing"]:
            if missing["direction"] == "end" and missing["text"] and any(
                extra["direction"] == "start" and missing["text"] in extra["text"] for extra in right["extra"]
            ):
                crossings.append({"from": left["id"], "to": right["id"], "text": missing["text"], "kind": "tail-moved-to-next"})
        for missing in right["missing"]:
            if missing["direction"] == "start" and missing["text"] and any(
                extra["direction"] == "end" and missing["text"] in extra["text"] for extra in left["extra"]
            ):
                crossings.append({"from": right["id"], "to": left["id"], "text": missing["text"], "kind": "head-moved-to-previous"})
        # Extra adjacent boundary text is a duplication even if neither row lost it.
        for extra in right["extra"]:
            if extra["direction"] == "start" and left["expectedNormalized"].endswith(extra["text"]):
                crossings.append({"from": left["id"], "to": right["id"], "text": extra["text"], "kind": "duplicate-boundary"})
    return {"status": "pass" if checks and all(c["status"] == "pass" for c in checks) and not crossings else "fail",
            "lines": checks, "adjacentIssues": crossings}


def decode_pcm(path):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
                             "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-c:a", "pcm_s16le", "-"],
                            capture_output=True)
    if result.returncode:
        raise ValueError("Cannot decode audio: " + result.stderr.decode(errors="replace")[-400:])
    if not result.stdout or len(result.stdout) % 2:
        raise ValueError("Decoded audio has no complete PCM samples")
    return result.stdout


def source_range(root, context):
    if not isinstance(context, dict) or any(key not in context for key in CONTEXT_KEYS):
        raise ValueError("sourceContext requires sourceFile/sourceSha256/startSeconds/endSeconds")
    source = project_file(root, context["sourceFile"])
    if sha256(source) != context["sourceSha256"]:
        raise ValueError("Original source audio hash changed")
    start, end = context["startSeconds"], context["endSeconds"]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)) or start < 0 or end <= start:
        raise ValueError("Invalid sourceContext range")
    pcm = decode_pcm(source)
    first, last = math.floor(start * SR + .5), math.floor(end * SR + .5)
    if first >= last or last > len(pcm) // 2:
        raise ValueError("sourceContext range is outside the original audio")
    return pcm[first * 2:last * 2], first, last


def verify_source_slice(root, line):
    """Exact PCM proof, not metadata alone. Recut with ``cut`` if this fails.

    Source is completely decoded/resampled before slicing; both source and slice
    use mono 48kHz PCM16. No lossy/compressed tolerance can certify sample identity.
    """
    if "sourceContext" not in line:
        return {"status": "not-required"}
    context = line["sourceContext"]
    expected, first, last = source_range(root, context)
    audio = project_file(root, line.get("audioFile"))
    actual = decode_pcm(audio)
    if actual != expected:
        raise ValueError("Slice PCM differs from sourceContext range: " + str(line.get("id", "?")) + "; recut from the fully resampled source using alignment_review.py cut")
    return {"status": "verified", "method": "exact-pcm16-mono-48000", "sourceSha256": context["sourceSha256"],
            "audioSha256": sha256(audio), "startSample": first, "endSample": last,
            "sampleRate": SR, "pcmSha256": hashlib.sha256(expected).hexdigest()}


def imported_bindings(root, spec):
    lines = [line for scene in spec.get("scenes", []) for line in scene.get("lines", []) if "audioFile" in line]
    if len({line.get("id") for line in lines}) != len(lines):
        raise ValueError("Imported line ids must be unique")
    result = []
    for line in lines:
        row = {key: line[key] for key in ("id", "text", "audioFile")}
        row["audioSha256"] = sha256(project_file(root, line["audioFile"]))
        if "sourceContext" in line:
            context = line["sourceContext"]
            if not isinstance(context, dict) or any(key not in context for key in CONTEXT_KEYS):
                raise ValueError("sourceContext requires sourceFile/sourceSha256/startSeconds/endSeconds")
            row["sourceContext"] = context
        result.append(row)
    return result


def binding_hash(bindings):
    return hashlib.sha256(canonical_bytes(bindings)).hexdigest()


def make_candidate(root, spec, transcripts):
    bindings = imported_bindings(root, spec)
    if not isinstance(transcripts, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in transcripts):
        raise ValueError("ASR input must be a list of objects with string ids")
    if len({row["id"] for row in transcripts}) != len(transcripts):
        raise ValueError("ASR input must be a list with unique ids")
    evidence = {row["id"]: row for row in transcripts}
    if set(evidence) != {row["id"] for row in bindings}:
        raise ValueError("ASR input must match the complete final imported-line mapping")
    rows = []
    for binding in bindings:
        transcript = evidence[binding["id"]]
        rows.append({**binding, "rawAsr": transcript["rawAsr"], "normalizations": transcript.get("normalizations", [])})
    return {"version": 1, "status": "pending", "bindingSha256": binding_hash(bindings),
            "review": None, "lines": rows, "checks": analyze_rows(rows)}


def validate_alignment(root, spec, verify_pcm=True):
    report_path = spec.get("audio", {}).get("alignmentReport")
    source_lines = [line for scene in spec.get("scenes", []) for line in scene.get("lines", []) if "sourceContext" in line]
    if not report_path:
        if source_lines:
            raise ValueError("Batched sourceContext audio requires audio.alignmentReport")
        return {"status": "not-required"}
    report_file = project_file(root, report_path)
    report = json.loads(report_file.read_text(encoding="utf-8"))
    if report.get("version") != 1 or report.get("status") != "reviewed":
        raise ValueError("Alignment report is not explicitly reviewed")
    review = report.get("review")
    if not isinstance(review, dict) or any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("reviewer", "method", "reviewedAt")):
        raise ValueError("Alignment review requires reviewer/method/reviewedAt")
    try:
        reviewed_at = datetime.fromisoformat(review["reviewedAt"].replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise ValueError("reviewedAt must be an ISO8601 timestamp with timezone") from None
    bindings = imported_bindings(root, spec)
    if report.get("bindingSha256") != binding_hash(bindings):
        raise ValueError("Alignment report is stale: final script/audio/source mapping changed")
    rows = report.get("lines")
    if not isinstance(rows, list) or len(rows) != len(bindings):
        raise ValueError("Alignment report must contain the complete final line mapping")
    for row, binding in zip(rows, bindings):
        if not isinstance(row, dict) or any(row.get(key) != value for key, value in binding.items()) or ("sourceContext" in row) != ("sourceContext" in binding):
            raise ValueError("Alignment row differs from final script/audio/source mapping")
        if not isinstance(row.get("rawAsr"), str) or not isinstance(row.get("normalizations", []), list):
            raise ValueError("Alignment rows need rawAsr and optional normalization list")
    analysis = analyze_rows(rows)
    if analysis["status"] != "pass":
        failures = [c["id"] for c in analysis["lines"] if c["status"] != "pass"]
        raise ValueError("Alignment text/boundary check failed: " + ", ".join(failures) + "; review the cut or merge the semantic passage")
    if verify_pcm:
        for line in source_lines:
            verify_source_slice(root, line)
    return {"status": "reviewed", "bindingSha256": binding_hash(bindings), "reportSha256": sha256(report_file),
            "lineCount": len(rows), "review": review, "pcmVerified": bool(verify_pcm and source_lines)}


def cut_source(root, context, output):
    root = Path(root).resolve()
    if not isinstance(output, str) or Path(output).is_absolute():
        raise ValueError("Cut output must be project-relative")
    destination = (root / output).resolve()
    if not destination.is_relative_to(root) or destination.exists():
        raise ValueError("Cut output must stay in project and must not already exist")
    if destination.suffix.lower() != ".wav":
        raise ValueError("Reproducible cut output must be WAV")
    pcm, first, last = source_range(root, context)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(SR); handle.writeframes(pcm)
    return {"audioFile": output, "sourceContext": context, "audioSha256": sha256(destination),
            "startSample": first, "endSample": last}


def merge_contiguous(root, lines, new_id, text, output):
    if len(lines) < 2:
        raise ValueError("Merge needs at least two consecutive script lines")
    if not isinstance(new_id, str) or not new_id or not isinstance(text, str) or not text.strip():
        raise ValueError("Merge needs a new id and explicit final spoken text")
    contexts = [line.get("sourceContext") for line in lines]
    if any(not isinstance(context, dict) for context in contexts):
        raise ValueError("Merge needs sourceContext on every selected line")
    for left, right in zip(contexts, contexts[1:]):
        if left["sourceFile"] != right["sourceFile"] or left["sourceSha256"] != right["sourceSha256"] or math.floor(left["endSeconds"] * SR + .5) != math.floor(right["startSeconds"] * SR + .5):
            raise ValueError("Merge ranges must be contiguous and from the same original source")
    context = {**contexts[0], "endSeconds": contexts[-1]["endSeconds"]}
    result = cut_source(root, context, output)
    return {"line": {"id": new_id, "text": text, "audioFile": output, "sourceContext": context},
            "replaces": [line["id"] for line in lines], "audioSha256": result["audioSha256"],
            "next": "Replace these consecutive lines in film.json; regenerate candidate ASR/review. Old report is invalid."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    candidate = sub.add_parser("candidate", aliases=["build"], help="Create pending review; ASR JSON: [{id,rawAsr,normalizations?:[{kind:homophone,from,to,reason}]}]")
    candidate.description = "ASR JSON is a list: [{\"id\":\"line-id\",\"rawAsr\":\"unaltered ASR text\",\"normalizations\":[]}]. Optional normalizations are equal-length {kind:homophone,from,to,reason} substitutions with evidence; never additions/deletions. Output stays pending until explicitly reviewed."
    candidate.add_argument("--asr", required=True, help="Project-relative UTF-8 raw ASR JSON list (one entry per final imported line)")
    candidate.add_argument("--output", required=True, help="New project-relative review JSON; refuses overwrite")
    sub.add_parser("validate", help="Validate current reviewed alignment and PCM origins")
    cut = sub.add_parser("cut", help="Cut exact source PCM; prints sourceContext for film.json")
    cut.add_argument("--source", required=True); cut.add_argument("--start", type=float, required=True)
    cut.add_argument("--end", type=float, required=True); cut.add_argument("--output", required=True)
    merge = sub.add_parser("merge", help="Create one semantic WAV and print proposed replacement; does not edit film.json")
    merge.add_argument("--line-ids", nargs="+", required=True); merge.add_argument("--new-id", required=True)
    merge.add_argument("--text", required=True); merge.add_argument("--output", required=True)
    for child in (candidate, cut, merge):
        child.add_argument("--project", default=argparse.SUPPRESS, help="Project root (default: current directory)")
    # Both global and post-command --project are accepted.
    sub.choices["validate"].add_argument("--project", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        root = Path(args.project).resolve()
        if args.command == "cut":
            context = {"sourceFile": args.source, "sourceSha256": sha256(project_file(root, args.source)),
                       "startSeconds": args.start, "endSeconds": args.end}
            result = cut_source(root, context, args.output)
        else:
            spec = json.loads(project_file(root, "content/film.json").read_text(encoding="utf-8"))
            if args.command == "validate":
                result = validate_alignment(root, spec)
            elif args.command in ("candidate", "build"):
                transcripts = json.loads(project_file(root, args.asr).read_text(encoding="utf-8"))
                result = make_candidate(root, spec, transcripts)
                destination = (root / args.output).resolve()
                if Path(args.output).is_absolute() or not destination.is_relative_to(root) or destination.exists():
                    raise ValueError("Candidate output must be a new project-relative file; preserve prior review")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            else:
                lines = [line for scene in spec["scenes"] for line in scene.get("lines", [])]
                ids = [line["id"] for line in lines]
                first = ids.index(args.line_ids[0])
                selected = lines[first:first + len(args.line_ids)]
                if [line["id"] for line in selected] != args.line_ids:
                    raise ValueError("Merge ids must be consecutive and in final script order")
                result = merge_contiguous(root, selected, args.new_id, args.text, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print("Alignment review failed: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
