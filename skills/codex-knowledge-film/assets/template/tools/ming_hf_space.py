"""Anonymous, public Gradio transport for the exact Ming 0.5B checkpoint.

No HF token, GPU-token headers, account creation, or automatic retries.
Schema verified at SPACE_URL/gradio_api/info on 2026-11-02.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SPACE_URL = "https://hugging-apps-ming-3-tts-05b.hf.space"
SPACE_ID = "hugging-apps/ming-3-tts-05b"
MODEL_ID = "inclusionAI/Ming-3.0-tts-0.5B"
ENDPOINT = "/builtin_voice"


def settings(spec):
    source = spec.get("hfSpace", {})
    result = {"spaceUrl": SPACE_URL, "seed": int(source.get("seed", 1895)),
              "cfg": float(source.get("cfg", 2)), "sigma": float(source.get("sigma", .25))}
    if not 1 <= result["cfg"] <= 5 or not 0 <= result["sigma"] <= 1:
        raise ValueError("HF Space cfg/sigma are outside the public API range")
    if source.get("spaceUrl", SPACE_URL) != SPACE_URL:
        raise ValueError("This backend is pinned to the verified Ming 0.5B public Space")
    return result


def payload(text, config, options):
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > 400:
        raise ValueError("HF Ming Space text must contain 1–400 characters")
    return {"text": text.strip(), "voice": config.get("voice", "US_James"),
            "seed": options["seed"], "cfg": options["cfg"], "sigma": options["sigma"]}


def cache_key(text, config, options):
    identity = {"transport": "hf-space", "spaceUrl": SPACE_URL, "spaceId": SPACE_ID,
                "model": MODEL_ID, "endpoint": ENDPOINT, "outputSampleRate": 48000,
                "adapterVersion": 1, **payload(text, config, options)}
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()[:24]


def parse_complete(sse):
    for frame in re.split(r"\r?\n\r?\n", sse):
        event, data = "", []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if event == "error":
            raise RuntimeError("HF Space stopped (no retry): " + " ".join(data)[:350])
        if event == "complete":
            result = json.loads("\n".join(data))
            if not isinstance(result, list) or not result or not isinstance(result[0], dict):
                raise RuntimeError("HF Space returned an unexpected audio result")
            return result[0]
    raise RuntimeError("HF Space ended without a complete audio event; no retry was made")


def _open(request, timeout):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        with exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"HF Space HTTP {exc.code}; stopped without retry: {detail[:350]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"HF Space connection stopped without retry: {exc}") from None


def generate(text, config, options, *, timeout=180):
    request = urllib.request.Request(
        SPACE_URL + "/gradio_api/call/v2/builtin_voice",
        data=json.dumps(payload(text, config, options), ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with _open(request, timeout) as response:
        job = json.loads(response.read(65536))
    event_id = job.get("event_id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9-]+", event_id):
        raise RuntimeError("HF Space did not return a valid event ID")
    with _open(SPACE_URL + "/gradio_api/call/builtin_voice/" + event_id, timeout) as response:
        file_data = parse_complete(response.read(1024 * 1024).decode("utf-8"))
    url = file_data.get("url")
    if not url and str(file_data.get("path", "")).startswith("/tmp/gradio/"):
        url = SPACE_URL + "/gradio_api/file=" + file_data["path"]
    parsed = urllib.parse.urlsplit(url or "")
    if parsed.scheme != "https" or parsed.netloc != urllib.parse.urlsplit(SPACE_URL).netloc:
        raise RuntimeError("HF Space audio download URL is outside the verified Space")
    with _open(url, timeout) as response:
        audio = response.read(100 * 1024 * 1024 + 1)
    if len(audio) > 100 * 1024 * 1024:
        raise RuntimeError("HF Space audio exceeded the 100 MB response limit")
    return audio, {"eventId": event_id, "sourceUrl": url, "transport": "hf-space",
                   "spaceId": SPACE_ID, "spaceUrl": SPACE_URL, "checkpoint": MODEL_ID,
                   "endpoint": ENDPOINT, **options}
