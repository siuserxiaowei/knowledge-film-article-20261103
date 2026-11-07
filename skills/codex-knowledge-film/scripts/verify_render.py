#!/usr/bin/env python3
"""Verify an encoded film technically and extract frames; do not claim semantic review."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys


def canonical(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def execute(args, timeout=300):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed: {result.stderr[-1200:]}")
    return result


def verify(project, video, frames=12):
    root = Path(project).expanduser().resolve()
    video = Path(video).expanduser()
    video = (video if video.is_absolute() else root / video).resolve()
    report_dir = root / "reviews"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "render-verification.json"
    report = {"createdAt": datetime.now(timezone.utc).isoformat(), "status": "checking",
              "video": str(video), "checks": {},
              "humanReview": {"visual": "pending", "spokenContent": "pending",
                             "note": "Metadata, decoding and frame extraction do not verify meaning or transcript."}}
    try:
        if not 0 <= frames <= 32:
            raise ValueError("Frame extraction count must be between 0 and 32")
        for tool in ("ffprobe", "ffmpeg"):
            if not shutil.which(tool):
                raise RuntimeError(tool + " is missing; install FFmpeg/FFprobe first")
        if not video.is_file():
            raise ValueError("Encoded video does not exist")
        timeline = json.loads((root / "src/generated/timeline.json").read_text(encoding="utf-8"))
        spec = json.loads((root / "content/film.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(canonical(spec), ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
        if timeline.get("ready") is not True or timeline.get("specHash") != digest:
            raise ValueError("Timeline is stale or not ready; prepare and render the current script")
        # Recheck the current source/review state, not only the frozen timeline.
        guard = root / "tools/check-film.mjs"
        if guard.is_file():
            checked = execute(["node", str(guard)])
            report["checks"]["currentInputs"] = checked.stdout.strip()
        elif spec.get("audio", {}).get("provenanceFile") or any(
                line.get("sourceContext") for scene in spec.get("scenes", []) for line in scene.get("lines", [])):
            raise ValueError("Source/review guard is missing from this project")
        info = json.loads(execute(["ffprobe", "-v", "error", "-show_entries",
              "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate,nb_frames,sample_rate,channels,duration",
              "-of", "json", str(video)]).stdout)
        picture = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
        sound = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
        if not picture:
            raise ValueError("No video stream")
        if (picture["width"], picture["height"]) != (timeline["width"], timeline["height"]):
            raise ValueError("Encoded dimensions differ from the timeline")
        if abs(float(Fraction(picture["r_frame_rate"])) - timeline["fps"]) > 1e-5:
            raise ValueError("Encoded frame rate differs from the timeline")
        duration = float(info["format"]["duration"])
        tolerance = max(.06, 2 / timeline["fps"])
        if abs(duration - timeline["durationSeconds"]) > tolerance:
            raise ValueError("Encoded duration differs from the timeline")
        if picture.get("nb_frames", "N/A") != "N/A" and int(picture["nb_frames"]) != timeline["durationInFrames"]:
            raise ValueError("Encoded frame count differs from the timeline")
        expected_audio = bool(timeline.get("audioSrc"))
        if expected_audio != bool(sound):
            raise ValueError("Encoded audio presence differs from prepared assets")
        if sound and (sound.get("sample_rate") != "48000" or sound.get("channels") != 2):
            raise ValueError("Expected 48kHz stereo soundtrack")
        execute(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-f", "null", "-"])
        report["checks"].update({"metadata": info, "fullDecode": "passed", "specHash": digest,
                                 "narrated": timeline["narrated"], "provenance": timeline.get("provenance")})
        if not timeline["narrated"]:
            report["humanReview"]["spokenContent"] = "not-applicable-no-narration"
        if sound:
            result = execute(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(video), "-vn", "-af",
                              "loudnorm=I=-16:TP=-1.5:print_format=json", "-f", "null", "-"])
            measured = json.loads(result.stderr[result.stderr.rfind("{"):result.stderr.rfind("}") + 1])
            report["checks"]["loudness"] = {"integratedLufs": measured["input_i"],
                                           "truePeakDbtp": measured["input_tp"], "lra": measured["input_lra"]}
            if float(measured["input_tp"]) > 0:
                raise ValueError("Encoded soundtrack exceeds 0 dBTP")
        else:
            report["humanReview"]["spokenContent"] = "not-applicable-no-soundtrack"
        video_hash = hashlib.sha256(video.read_bytes()).hexdigest()
        visual = hashlib.sha256()
        for source in sorted((root / "src").rglob("*")):
            if source.is_file() and source.suffix in (".ts", ".tsx", ".css", ".svg"):
                visual.update(str(source.relative_to(root)).encode() + b"\0" + source.read_bytes() + b"\0")
        report["checks"]["reviewBinding"] = {"specSha256": digest, "videoSha256": video_hash,
                                                "visualCodeSha256": visual.hexdigest()}
        if timeline.get("audioSrc"):
            prepared_audio = (root / "public" / timeline["audioSrc"]).resolve()
            prepared_audio.relative_to((root / "public").resolve())
            report["checks"]["reviewBinding"]["preparedAudioSha256"] = hashlib.sha256(prepared_audio.read_bytes()).hexdigest()
        for field in ("alignmentReport", "provenanceFile"):
            if spec.get("audio", {}).get(field):
                evidence = (root / spec["audio"][field]).resolve()
                evidence.relative_to(root)
                report["checks"]["reviewBinding"][field + "Sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
        if frames:
            folder = report_dir / "encoded-frames" / f"{video_hash[:16]}-{frames}"
            folder.mkdir(parents=True, exist_ok=True)
            times = [max(0, min(duration - .05, .2 + max(0, duration - .4) * i / max(1, frames - 1))) for i in range(frames)]
            files = []
            for index, timestamp in enumerate(times):
                target = folder / f"frame-{index:02d}.jpg"
                execute(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", str(timestamp), "-i", str(video),
                         "-frames:v", "1", "-vf", "scale=480:-2", str(target)])
                files.append(str(target.relative_to(root)))
            sheet = report_dir / "contact-sheet.jpg"
            cols, rows = min(4, frames), math.ceil(frames / min(4, frames))
            execute(["ffmpeg", "-v", "error", "-y", "-nostdin", "-framerate", "1", "-i", str(folder / "frame-%02d.jpg"),
                     "-vf", f"tile={cols}x{rows}:padding=4:margin=4:color=0x181818", "-frames:v", "1", str(sheet)])
            report["checks"]["frames"] = {"timesSeconds": times, "files": files,
                                          "contactSheet": str(sheet.relative_to(root)), "reviewed": False}
        report["videoSha256"] = video_hash
        report["status"] = "technical-passed"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
    pending = report_path.with_suffix(".pending.json")
    pending.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--video", type=Path, default=Path("out/film.mp4"))
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    report = verify(args.project, args.video, args.frames)
    print(json.dumps({"status": report["status"], "error": report.get("error"),
                      "report": str(args.project.resolve() / "reviews/render-verification.json"),
                      "humanReview": report["humanReview"]}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "technical-passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
