"""Prepare deterministic timelines and soundtracks for knowledge films.

No Python packages are required. FFmpeg/FFprobe handle media processing.
--dry-run never reads credentials, writes files, or calls a model.
Explicit --mode/--backend options persist audio settings to content/film.json.
--sample writes separate sample outputs, never a ready full-film timeline.
"""
from __future__ import annotations

import argparse
from array import array
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave

import audio_guard
import ming_hf_space
import ming_tts

ROOT = Path(__file__).resolve().parent.parent
SR = 48000
MODEL = "Ming-3.0-tts-0.5B"
THEME = {"background": "#090705", "foreground": "#EEE8D8", "accent": "#C9AD68", "danger": "#C56052"}
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class PrepareError(ValueError):
    pass


def canonical(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def json_bytes(value):
    return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def spec_hash(spec):
    return hashlib.sha256(json_bytes(spec)).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    pending.replace(path)


def seconds(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise PrepareError(label + " must be a finite nonnegative duration")
    return float(value)


def to_frame(value, fps):
    # Nonnegative Math.round-compatible conversion, not Python's ties-to-even.
    return int(math.floor(value * fps + .5))


def validate_spec(spec):
    json_bytes(spec)
    if spec.get("version") != 1 or not ID.fullmatch(spec.get("id", "")):
        raise PrepareError("film.json needs version=1 and a lowercase hyphenated id")
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        raise PrepareError("Film title must be a non-empty string")
    for name in ("width", "height"):
        value = spec.get(name, 1920 if name == "width" else 1080)
        if type(value) is not int or value < 16 or value % 2:
            raise PrepareError(name + " must be a positive even integer of at least 16")
    fps = spec.get("fps", 30)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not math.isfinite(fps) or not 0 < fps <= 120:
        raise PrepareError("fps must be between 0 and 120")
    if not isinstance(spec.get("theme", {}), dict):
        raise PrepareError("theme must be an object")
    audio = spec.get("audio", {})
    if not isinstance(audio, dict) or audio.get("mode", "silent") not in ("silent", "ming", "import"):
        raise PrepareError("audio.mode must be silent, ming, or import")
    if "music" in audio and type(audio["music"]) is not bool:
        raise PrepareError("audio.music must be a boolean")
    if audio.get("mode") == "ming":
        if audio.get("references"):
            raise PrepareError("The template supports built-in Ming voices; voice cloning requires an explicitly implemented references adapter")
        if audio.get("backend", "hf-space") not in ("official", "hf-space") or audio.get("model", MODEL) != MODEL:
            raise PrepareError("Ming preparation requires the exact Ming-3.0-tts-0.5B model and an official/hf-space backend")
        if not isinstance(audio.get("voice", "灵小锋"), str) or not audio.get("voice", "灵小锋").strip():
            raise PrepareError("Ming voice must be a non-empty string")
    pacing = spec.get("pacing", {})
    for name, default in (("leadSeconds", .3), ("tailSeconds", .45), ("sceneGapSeconds", .3)):
        seconds(pacing.get(name, default), "pacing." + name)
    scenes = spec.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        raise PrepareError("Film must contain at least one scene")
    seen_scenes, seen_lines = set(), set()
    for scene in scenes:
        if not isinstance(scene, dict) or not ID.fullmatch(scene.get("id", "")) or scene["id"] in seen_scenes:
            raise PrepareError("Each scene needs a unique lowercase hyphenated id")
        seen_scenes.add(scene["id"])
        if not isinstance(scene.get("title", ""), str) or not isinstance(scene.get("visual", {}), dict):
            raise PrepareError("Scene title/visual has the wrong type")
        if not isinstance(scene.get("kind"), str) or not scene["kind"]:
            raise PrepareError("Each scene needs a kind")
        lines = scene.get("lines", [])
        if not isinstance(lines, list):
            raise PrepareError("Scene lines must be an array")
        if not lines:
            seconds(scene.get("durationSeconds", 3), "scene.durationSeconds", .1)
        for line in lines:
            if not isinstance(line, dict) or not ID.fullmatch(line.get("id", "")) or line["id"] in seen_lines:
                raise PrepareError("Line ids must be unique across the whole film")
            seen_lines.add(line["id"])
            if not isinstance(line.get("text"), str) or not line["text"].strip():
                raise PrepareError("Every caption/narration line needs non-empty text")
            if "silentSeconds" in line:
                seconds(line["silentSeconds"], "line.silentSeconds", .1)
    return spec


def safe_error(error, key=None):
    detail = str(error)
    if key:
        detail = detail.replace(key, "[redacted]")
    return re.sub(r"(?i)bearer\s+[^\s\"']+", "Bearer [redacted]", detail)[:600]


def load_api_key(root):
    import os
    value = os.environ.get("MING_API_KEY", "").strip()
    if value:
        return value
    env = Path(root) / ".env"
    if not env.is_file():
        return None
    result = None
    for raw in env.read_text(encoding="utf-8").lstrip("\ufeff").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        name, value = raw.split("=", 1)
        if name.strip() != "MING_API_KEY":
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith("#")):
                raise PrepareError("Malformed MING_API_KEY assignment in project .env")
            result = value[1:end]
        else:
            result = value.split(" #", 1)[0].strip()
    return result or None


def media_command(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True)
    if result.returncode:
        raise PrepareError("Media processing failed: " + result.stderr[-1000:])
    return result.stdout, result.stderr


def ffmpeg(*args):
    return media_command("ffmpeg", "-hide_banner", "-nostdin", *args)


def probe(path):
    output, _ = media_command("ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                              "stream=sample_rate,channels:format=duration", "-of", "json", path)
    data = json.loads(output)
    if not data.get("streams"):
        raise PrepareError("Input has no audio stream")
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise PrepareError("Input audio is empty or has invalid duration")
    return {"durationSeconds": duration, "sampleRate": int(data["streams"][0]["sample_rate"]),
            "channels": int(data["streams"][0]["channels"])}


def local_audio(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise PrepareError("Imported line.audioFile must be a project-relative media path")
    path = (Path(root) / value).resolve()
    try:
        path.relative_to(Path(root).resolve())
    except ValueError:
        raise PrepareError("Imported audio leaves the project directory") from None
    if not path.is_file() or path.suffix.lower() not in (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus"):
        raise PrepareError("Imported audio file is missing or has an unsupported media extension")
    return path


def official_config(audio):
    return {"provider": "ming", "model": MODEL, "voice": audio.get("voice", "灵小锋"),
            **{key: audio[key] for key in ("instructions", "speed", "pitch", "volume", "stream_format") if key in audio}}


def hf_options(audio):
    return ming_hf_space.settings({"hfSpace": {key: audio[key] for key in ("seed", "cfg", "sigma") if key in audio}})


def source_identity(root, line, audio):
    mode, backend = audio.get("mode", "silent"), audio.get("backend", "hf-space")
    if mode == "import":
        source = local_audio(root, line.get("audioFile"))
        identity = audio_guard.import_identity(root, line, audio)
        return hashlib.sha256(json_bytes(identity)).hexdigest(), identity, source
    if backend == "official":
        payload = ming_tts.build_payload(line["text"], official_config(audio), sample_rate=SR)
        identity = {"transport": "official", "endpoint": ming_tts.ENDPOINT, "payload": payload,
                    "adapterVersion": 1, "processingSampleRate": SR}
    else:
        payload = ming_hf_space.payload(line["text"], official_config(audio), hf_options(audio))
        identity = {"transport": "hf-space", "spaceId": ming_hf_space.SPACE_ID,
                    "checkpoint": ming_hf_space.MODEL_ID, "endpoint": ming_hf_space.ENDPOINT,
                    "spaceUrl": ming_hf_space.SPACE_URL, "payload": payload,
                    "adapterVersion": 1, "processingSampleRate": SR}
    return hashlib.sha256(json_bytes(identity)).hexdigest(), identity, None


def trim_and_fade(source, output):
    """Decode to mono PCM16, trim edges only, and preserve internal pauses."""
    with tempfile.TemporaryDirectory(prefix="knowledge-clip-") as temp:
        decoded = Path(temp) / "decoded.wav"
        ffmpeg("-v", "error", "-y", "-i", source, "-vn", "-ac", "1", "-ar", SR,
               "-c:a", "pcm_s16le", decoded)
        with wave.open(str(decoded), "rb") as handle:
            samples = array("h", handle.readframes(handle.getnframes()))
        if sys.byteorder != "little":
            samples.byteswap()
        peak = max((abs(value) for value in samples), default=0)
        if peak < 2:
            raise PrepareError("Narration audio is silent")
        threshold = max(1, peak * 10 ** (-45 / 20))
        start = next(index for index, value in enumerate(samples) if abs(value) > threshold)
        last = len(samples) - 1 - next(index for index, value in enumerate(reversed(samples)) if abs(value) > threshold)
        start, end = max(0, start - round(.03 * SR)), min(len(samples), last + 1 + round(.08 * SR))
        fitted = samples[start:end]
        edge = min(round(.005 * SR), len(fitted) // 2)
        for index in range(edge):
            gain = math.sin(index / max(1, edge - 1) * math.pi / 2) ** 2
            fitted[index] = round(fitted[index] * gain)
            fitted[-index - 1] = round(fitted[-index - 1] * gain)
        if sys.byteorder != "little":
            fitted.byteswap()
        output.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(SR)
            handle.writeframes(fitted.tobytes())
        return {"rawDurationSeconds": len(samples) / SR, "durationSeconds": len(fitted) / SR,
                "trimStartSeconds": start / SR, "trimEndSeconds": (len(samples) - end) / SR,
                "edgeFadeMs": 5, "tempoRate": 1.0}


def empty_timeline(spec, reason):
    fps = spec.get("fps", 30)
    fps = fps if not isinstance(fps, bool) and isinstance(fps, (int, float)) and math.isfinite(fps) and 0 < fps <= 120 else 30
    width, height = spec.get("width", 1920), spec.get("height", 1080)
    width = width if type(width) is int and width >= 16 and not width % 2 else 1920
    height = height if type(height) is int and height >= 16 and not height % 2 else 1080
    theme = spec.get("theme", {})
    theme = theme if isinstance(theme, dict) else {}
    return {"version": 1, "ready": False, "specHash": spec_hash(spec), "title": spec.get("title", "Knowledge Film"),
            "fps": fps, "width": width, "height": height,
            "durationSeconds": 1, "durationInFrames": to_frame(1,fps), "audioSrc": None, "narrated": False,
            "provenance": {"status": "not-ready", "reason": reason}, "theme": {**THEME, **theme},
            "scenes": [], "captions": []}


def invalidate(root, spec, reason):
    write_json(Path(root) / "src/generated/timeline.json", empty_timeline(spec, reason))


def srt_time(value):
    ms = round(value * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def write_srt(path, captions):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(f"{index}\n{srt_time(line['startSeconds'])} --> {srt_time(line['endSeconds'])}\n{line['text']}"
                                for index, line in enumerate(captions, 1)) + "\n", encoding="utf-8")


def measure_loudness(path, target=-16):
    _, stderr = ffmpeg("-i", path, "-af", f"loudnorm=I={target}:TP=-2:LRA=11:print_format=json", "-f", "null", "-")
    result = json.loads(stderr[stderr.rfind("{"):stderr.rfind("}") + 1])
    return {"integratedLufs": float(result["input_i"]), "truePeakDbfs": float(result["input_tp"])}


def mix_audio(root, timeline, lines, audio, sample=False):
    duration, narrated = timeline["durationSeconds"], timeline["narrated"]
    frames = round(duration * SR)
    exact = f"apad=whole_len={frames},atrim=end_sample={frames},asetpts=N/SR/TB"
    music = audio.get("music", True)
    if not narrated and not music:
        return None, None
    suffix = "sample-" if sample else ""
    directory = Path(root) / "public/audio"
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{suffix}mix.wav"
    with tempfile.TemporaryDirectory(prefix="knowledge-mix-") as temp:
        temp = Path(temp)
        music_path = temp / "music.wav"
        if music:
            raw_expr = "0.009*(sin(2*PI*110*t)+0.35*sin(2*PI*165*t)+0.22*sin(2*PI*220*t))"
            ffmpeg("-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc={raw_expr}:s={SR}:d={duration}",
                   "-af", f"afade=t=in:d=0.5,afade=t=out:st={max(0,duration-.8)}:d=0.8,loudnorm=I=-28:TP=-5:LRA=7,aresample={SR}",
                   "-ac", "2", "-c:a", "pcm_s24le", music_path)
        if narrated:
            pcm = bytearray(frames * 2)
            for line in lines:
                if "preparedAudio" not in line:
                    continue
                with wave.open(str(Path(root) / line["preparedAudio"]), "rb") as handle:
                    data = handle.readframes(handle.getnframes())
                start = round(line["startSeconds"] * SR) * 2
                if start + len(data) > len(pcm):
                    raise PrepareError("Narration extends beyond the planned timeline")
                pcm[start:start + len(data)] = data
            voice = temp / "voice.wav"
            with wave.open(str(voice), "wb") as handle:
                handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(SR); handle.writeframes(pcm)
            voice_norm = temp / "voice-normalized.wav"
            ffmpeg("-v", "error", "-y", "-i", voice, "-af", f"loudnorm=I=-17:TP=-2.5:LRA=9,aresample={SR}",
                   "-ac", "1", "-c:a", "pcm_s24le", voice_norm)
            if music:
                duck = max(0, min(30, float(audio.get("duckDb", 12))))
                activity = []
                for line in lines:
                    a, b = line["startSeconds"], line["actualVoiceEndSeconds"]
                    activity.append(f"max(0,min(1,(t-({a}-.06))/.06))*max(0,min(1,({b}+.3-t)/.3))")
                maximum = "min(1," + "+".join("(" + item + ")" for item in activity) + ")" if activity else "0"
                gain = f"1-({1-10**(-duck/20)})*({maximum})"
                filt = (f"[0:a]pan=stereo|c0=c0|c1=c0[voice];[1:a]volume='{gain}':eval=frame[bg];"
                        f"[voice][bg]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-2:LRA=11,aresample={SR},"
                        f"{exact}[mix]")
                ffmpeg("-v", "error", "-y", "-i", voice_norm, "-i", music_path, "-filter_complex", filt,
                       "-map", "[mix]", "-ac", "2", "-c:a", "pcm_s24le", final)
            else:
                ffmpeg("-v", "error", "-y", "-i", voice_norm, "-af",
                       f"loudnorm=I=-16:TP=-2:LRA=11,aresample={SR},{exact}",
                       "-ac", "2", "-c:a", "pcm_s24le", final)
        else:
            ffmpeg("-v", "error", "-y", "-i", music_path, "-af",
                   f"loudnorm=I=-24:TP=-4:LRA=9,aresample={SR},{exact}",
                   "-ac", "2", "-c:a", "pcm_s24le", final)
    info = probe(final)
    if info["sampleRate"] != SR or info["channels"] != 2 or abs(info["durationSeconds"] - duration) > .025:
        raise PrepareError("Final mix has incorrect sample rate, channels or duration")
    stats = measure_loudness(final, -16 if narrated else -24)
    if not all(math.isfinite(value) for value in stats.values()) or stats["truePeakDbfs"] > -.5:
        raise PrepareError("Final mix is silent/non-finite or exceeds the peak limit")
    return str(final.relative_to(Path(root) / "public")), stats


def prepare(root, spec, *, sample=False, official_synth=None, hf_synth=None, clock=time.monotonic, sleeper=time.sleep):
    root = Path(root).resolve()
    validate_spec(spec)
    mode = spec.get("audio", {}).get("mode", "silent")
    audio = spec.get("audio", {})
    backend = audio.get("backend", "hf-space")
    has_lines = any(scene.get("lines") for scene in spec["scenes"])
    report_path = root / "content" / ("sample-build-report.json" if sample else "build-report.json")
    report = {"version": 1, "status": "building", "sample": sample, "specHash": spec_hash(spec),
              "mode": mode, "networkRequests": 0, "lines": [], "model": MODEL if mode == "ming" and has_lines else None,
              "voice": audio.get("voice", "灵小锋") if mode == "ming" and has_lines else None,
              "transport": backend if mode == "ming" else "imported-unverified-provider" if mode == "import" else "local-silent",
              "ignoredParameters": [key for key in ("instructions", "speed", "pitch", "volume") if key in audio] if mode == "ming" and backend == "hf-space" else []}
    if not sample:
        invalidate(root, spec, "preparing current film")
    key, last_request = None, None
    try:
        if (mode != "silent" or audio.get("music", True)) and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            raise PrepareError("Install FFmpeg and FFprobe before preparing audio")
        inputs = audio_guard.collect_inputs(root, spec) if mode == "import" else None
        report["audioInputs"] = inputs
        report["reviewState"] = {"technical": "building", "alignment": audio_guard.review_state(root, spec),
                                "provenance": "observed-source-evidence" if inputs and inputs["provenance"] else
                                              "unverified-import" if mode == "import" else "adapter-recorded" if mode == "ming" else "not-required",
                                "visual": "pending", "encoded": "pending"}
        fps = spec.get("fps", 30)
        lead = spec.get("pacing", {}).get("leadSeconds", .3)
        tail = spec.get("pacing", {}).get("tailSeconds", .45)
        gap = spec.get("pacing", {}).get("sceneGapSeconds", .3)
        scenes, captions, cursor, count = [], [], 0.0, 0
        limit = 3 if sample else math.inf
        for scene in spec["scenes"]:
            if count >= limit:
                break
            start = cursor
            selected = scene.get("lines", [])
            if selected:
                cursor += lead
                for line in selected:
                    if count >= limit:
                        break
                    count += 1
                    entry = {"id": line["id"], "sceneId": scene["id"], "text": line["text"],
                             "startSeconds": cursor}
                    if mode == "silent":
                        length = line.get("silentSeconds", max(2.5, min(8, len(line["text"]) / 4.5 + .5)))
                        entry.update({"durationBasis": "explicit-silent-window" if "silentSeconds" in line else "estimated-reading-time",
                                      "estimated": "silentSeconds" not in line, "durationSeconds": length})
                    else:
                        cache, identity, imported = source_identity(root, line, audio)
                        cache_dir = root / ".cache/audio" / cache
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        extension = imported.suffix if imported else ".wav"
                        raw = cache_dir / ("source" + extension)
                        receipt_file = cache_dir / "source.json"
                        reused = raw.is_file() and receipt_file.is_file()
                        receipt = json.loads(receipt_file.read_text()) if reused else None
                        if reused and (receipt.get("sourceSha256") != file_hash(raw) or receipt.get("identity") != identity):
                            raise PrepareError("Cached source audio was changed; inspect its provenance before regenerating")
                        if not reused:
                            if mode == "import":
                                shutil.copyfile(imported, raw)
                                if file_hash(raw) != identity["sourceSha256"]:
                                    raise PrepareError("Imported audio changed while it was being copied")
                                detail = {"provider": "imported-unverified-provider", "sourceFile": str(imported.relative_to(root)),
                                          "claimedModel": audio.get("model"), "modelVerified": False}
                                if "sourceContext" in line:
                                    detail["sourceContext"] = copy.deepcopy(line["sourceContext"])
                                if inputs and inputs["provenance"]:
                                    detail["recordedSourceEvidence"] = inputs["provenance"]
                            else:
                                if last_request is not None and clock() - last_request < .55:
                                    sleeper(.55 - (clock() - last_request))
                                last_request = clock()
                                if backend == "official":
                                    if key is None:
                                        key = load_api_key(root)
                                    if not key:
                                        raise PrepareError("Official Ming needs MING_API_KEY; use an authorized account or import existing narration")
                                    report["networkRequests"] += 1
                                    returned = (official_synth or ming_tts.synth)(line["text"], official_config(audio), sample_rate=SR, api_key=key)
                                    ming_tts.validate_wav(returned, sample_rate=SR)
                                    detail = {"provider": "ming", "model": MODEL, "voice": audio.get("voice", "灵小锋"),
                                              "transport": "official", "endpoint": ming_tts.ENDPOINT}
                                else:
                                    report["networkRequests"] += 1
                                    returned, detail = (hf_synth or ming_hf_space.generate)(line["text"], official_config(audio), hf_options(audio))
                                    ming_tts.validate_wav(returned)
                                    detail = {**detail, "provider": "ming", "model": MODEL, "voice": audio.get("voice", "灵小锋")}
                                pending = raw.with_name(raw.name + ".pending")
                                pending.write_bytes(returned)
                                pending.replace(raw)
                            receipt = {"identity": identity, "sourceSha256": file_hash(raw), "provenance": detail}
                            write_json(receipt_file, receipt)
                        processed = cache_dir / "prepared.wav"
                        measurements = trim_and_fade(raw, processed)
                        length = measurements["durationSeconds"]
                        entry.update({**measurements, "durationBasis": "measured-audio", "estimated": False,
                                      "cacheKey": cache, "cacheReused": reused,
                                      "sourceSha256": receipt["sourceSha256"], "provenance": receipt["provenance"],
                                      "sourceMedia": probe(raw), "processingSampleRate": SR,
                                      "sourcePath": str(raw.relative_to(root)),
                                      "cacheReceipt": str(receipt_file.relative_to(root)),
                                      "cacheReceiptSha256": file_hash(receipt_file),
                                      "preparedSha256": file_hash(processed),
                                      "preparedAudio": str(processed.relative_to(root))})
                    entry["actualVoiceEndSeconds"] = cursor + length if mode != "silent" else None
                    caption_end = cursor + length + tail
                    captions.append({"id": line["id"], "sceneId": scene["id"], "text": line["text"],
                                     "startSeconds": cursor, "endSeconds": caption_end,
                                     "startFrame": to_frame(cursor, fps), "endFrame": to_frame(caption_end, fps)})
                    cursor = caption_end
                    report["lines"].append(entry)
                    write_json(report_path, report)
            else:
                cursor += scene.get("durationSeconds", 3)
            cursor += gap
            end = cursor
            scenes.append({"id": scene["id"], "kind": scene["kind"], "title": scene.get("title", ""),
                           "visual": copy.deepcopy(scene.get("visual", {})), "startSeconds": start,
                           "endSeconds": end, "startFrame": to_frame(start, fps),
                           "durationInFrames": to_frame(end, fps) - to_frame(start, fps)})
        total_frames = to_frame(cursor, fps)
        if total_frames < 1:
            raise PrepareError("Film duration is less than one frame")
        duration = total_frames / fps
        scenes[-1]["endSeconds"] = duration
        provenance = {"mode": mode, "transport": report["transport"], "model": report["model"],
                      "voice": report["voice"], "syntheticSpeech": mode == "ming" and bool(report["lines"]),
                      "importedProviderVerified": False if mode == "import" else None,
                      "timing": "measured-audio" if mode != "silent" else "silent-reading-windows",
                      "sourceEvidence": inputs["provenance"] if inputs else None,
                      "reviewState": report["reviewState"]}
        timeline = {"version": 1, "ready": True, "specHash": spec_hash(spec), "title": spec["title"],
                    "fps": fps, "width": spec.get("width", 1920), "height": spec.get("height", 1080),
                    "durationSeconds": duration, "durationInFrames": total_frames, "audioSrc": None,
                    "narrated": mode != "silent" and bool(report["lines"]), "provenance": provenance,
                    "theme": {**THEME, **spec.get("theme", {})}, "scenes": scenes, "captions": captions}
        audio_src, loudness = mix_audio(root, timeline, report["lines"], audio, sample)
        timeline["audioSrc"] = audio_src
        report["reviewState"]["technical"] = "complete"
        report.update({"status": "complete", "durationSeconds": duration, "durationInFrames": total_frames,
                       "narrated": timeline["narrated"], "audioSrc": audio_src, "loudness": loudness,
                       "audioSha256": file_hash(root / "public" / audio_src) if audio_src else None,
                       "captionCount": len(captions), "sceneCount": len(scenes),
                       "plannedDurationSeconds": cursor})
        write_json(report_path, report)
        write_srt(root / "public" / ("sample-captions.srt" if sample else "captions.srt"), captions)
        write_json(root / "src/generated" / ("sample-timeline.json" if sample else "timeline.json"), timeline)
        return report
    except Exception as exc:
        if "reviewState" in report:
            report["reviewState"]["technical"] = "failed"
        report.update({"status": "failed", "error": safe_error(exc, key)})
        write_json(report_path, report)
        if not sample:
            invalidate(root, spec, report["error"])
        raise PrepareError(report["error"]) from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT)
    parser.add_argument("--mode", choices=("silent", "ming", "import"))
    parser.add_argument("--backend", choices=("official", "hf-space"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args(argv)
    root = args.project.resolve()
    spec = None
    try:
        film_path = root / "content/film.json"
        spec = json.loads(film_path.read_text(encoding="utf-8"))
        original = spec_hash(spec)
        if args.mode or args.backend:
            audio = spec.setdefault("audio", {})
            if args.mode:
                audio["mode"] = args.mode
            if args.backend:
                audio["backend"] = args.backend
        validate_spec(spec)
        if args.dry_run:
            lines = [line for scene in spec["scenes"] for line in scene.get("lines", [])]
            print(json.dumps({"dryRun": True, "writes": 0, "networkRequests": 0, "credentialsRead": False,
                              "mode": spec.get("audio", {}).get("mode", "silent"), "specHash": spec_hash(spec),
                              "scenes": len(spec["scenes"]), "lines": min(3, len(lines)) if args.sample else len(lines),
                              "timing": "requires real audio measurements" if spec.get("audio", {}).get("mode") != "silent" else "silent-reading-windows"},
                             ensure_ascii=False, indent=2))
            return 0
        if spec_hash(spec) != original:
            write_json(film_path, spec)
            invalidate(root, spec, "audio settings changed; full preparation required")
        result = prepare(root, spec, sample=args.sample)
        print(json.dumps({key: result.get(key) for key in ("status", "sample", "mode", "transport", "model", "networkRequests", "captionCount", "sceneCount", "durationSeconds", "audioSrc", "loudness")}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # Avoid retaining a stale ready timeline even if JSON/spec validation fails.
        if not args.dry_run and not args.sample:
            fallback = spec if isinstance(spec, dict) else {"version": 1, "title": "Invalid film"}
            try:
                invalidate(root, fallback, safe_error(exc))
            except Exception:
                write_json(root / "src/generated/timeline.json", {"version": 1, "ready": False,
                           "specHash": "invalid", "title": "Invalid film", "fps": 30, "width": 1920, "height": 1080,
                           "durationSeconds": 1, "durationInFrames": 30, "audioSrc": None, "narrated": False,
                           "theme": THEME, "scenes": [], "captions": [], "provenance": {"status": "not-ready"}})
        print("Film preparation stopped: " + safe_error(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
