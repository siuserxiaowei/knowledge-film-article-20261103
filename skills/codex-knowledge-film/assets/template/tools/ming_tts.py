"""Ant Ling Ming TTS adapter. No dependencies, implicit retries, or key logging.

API contract: https://developer.ant-ling.com/zh-CN/docs/api-reference/audio/tts/
Verified 2026-11-02. Keys stay in MING_API_KEY and never enter the cache key.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import struct
import urllib.error
import urllib.request
from collections.abc import Mapping

ENDPOINT = "https://api.ant-ling.com/v1/audio/speech"
MODEL = "Ming-3.0-tts-0.5B"
MAX_RESPONSE_BYTES = 100 * 1024 * 1024


class MingTTSError(RuntimeError):
    """An actionable synthesis error, with credentials removed."""


def build_payload(text: str, config: Mapping, *, sample_rate: int = 48000) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 2048:
        raise ValueError("Ming input must contain 1–2048 characters")
    if config.get("provider", "ming") != "ming":
        raise ValueError("This adapter only supports provider='ming'")
    if sample_rate not in (8000, 16000, 22050, 24000, 44100, 48000):
        raise ValueError("Unsupported Ming sample rate")
    payload = {
        "model": config.get("model", MODEL),
        "input": text,
        "response_format": "wav",
        "sample_rate": sample_rate,
    }
    if not isinstance(payload["model"], str) or not payload["model"]:
        raise ValueError("Ming model must be a non-empty string")
    if config.get("voice") and config.get("references"):
        raise ValueError("Choose either voice or references, not both")
    if config.get("voice"):
        if not isinstance(config["voice"], str):
            raise ValueError("Ming voice must be a string")
        payload["voice"] = config["voice"]
    if config.get("references"):
        references = config["references"]
        if not isinstance(references, list) or len(references) != 1:
            raise ValueError("Ming supports exactly one voice reference")
        ref = references[0]
        if not isinstance(ref, dict) or not isinstance(ref.get("text"), str) or not ref["text"].strip():
            raise ValueError("The voice reference needs its verbatim transcript")
        audio = ref.get("audio", "")
        if not isinstance(audio, str) or not audio.startswith("data:audio/wav;base64,"):
            raise ValueError("Reference audio must be a data:audio/wav;base64,... URL")
        encoded = audio.split(",", 1)[1]
        if len(encoded.encode()) > 10 * 1024 * 1024:
            raise ValueError("Base64 reference audio exceeds 10 MB")
        try:
            reference_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid reference audio Base64") from exc
        info = validate_wav(reference_bytes)
        if info["duration"] > 30:
            raise ValueError("Reference audio exceeds 30 seconds")
        payload["references"] = [{"audio": audio, "text": ref["text"]}]
    if config.get("instructions"):
        if not isinstance(config["instructions"], str):
            raise ValueError("Ming instructions must be a string")
        payload["instructions"] = config["instructions"]
    for key, low, high in (("speed", 0.25, 4.0), ("volume", 0.5, 2.0), ("pitch", 0.5, 2.0)):
        if key in config:
            value = config[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                raise ValueError(f"Ming {key} must be in [{low}, {high}]")
            payload[key] = value
    if config.get("stream_format"):
        if config["stream_format"] != "sse":
            raise ValueError("Ming TTS streaming only supports 'sse'")
        payload["stream_format"] = "sse"
    return payload


def cache_key(text: str, config: Mapping, *, sample_rate: int = 48000) -> str:
    payload = build_payload(text, config, sample_rate=sample_rate)
    # Reference identity is content based; credentials and machine paths are excluded.
    for ref in payload.get("references", []):
        ref["audio"] = "sha256:" + hashlib.sha256(ref["audio"].encode()).hexdigest()
    canonical = json.dumps({"provider": "ming", "adapter_version": 1, **payload},
                           ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def validate_wav(audio: bytes, *, sample_rate: int | None = None) -> dict:
    """Check RIFF/WAVE structure, including PCM24/float WAV, without audio libraries."""
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise MingTTSError("Ming did not return a valid WAV file")
    declared_end = struct.unpack_from("<I", audio, 4)[0] + 8
    if declared_end > len(audio):
        raise MingTTSError("Ming returned a truncated WAV file")
    offset, fmt, data_size = 12, None, None
    while offset + 8 <= declared_end:
        chunk, size = audio[offset:offset + 4], struct.unpack_from("<I", audio, offset + 4)[0]
        end = offset + 8 + size
        if end > declared_end:
            raise MingTTSError("Ming returned a truncated WAV chunk")
        if chunk == b"fmt " and size >= 16:
            encoding, channels, rate, byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", audio, offset + 8)
            fmt = (encoding, channels, rate, byte_rate, block_align, bits)
        elif chunk == b"data":
            data_size = size
        offset = end + size % 2
    if fmt is None or not data_size or fmt[1] < 1 or fmt[2] < 1 or fmt[3] < 1 or fmt[4] < 1:
        raise MingTTSError("Ming returned a WAV without usable audio frames")
    if sample_rate is not None and fmt[2] != sample_rate:
        raise MingTTSError(f"Ming returned {fmt[2]} Hz; expected {sample_rate} Hz")
    return {"sample_rate": fmt[2], "channels": fmt[1], "duration": data_size / fmt[3]}


def _safe_detail(value: object, key: str) -> str:
    detail = str(value)
    if key:
        detail = detail.replace(key, "[redacted]")
    return re.sub(r"(?i)bearer\s+[^\s\"']+", "Bearer [redacted]", detail)[:300]


def _error_detail(body: bytes, key: str) -> str:
    try:
        data = json.loads(body)
        error = data.get("error", data)
        message = error.get("message", error.get("code", "API error")) if isinstance(error, dict) else error
        return _safe_detail(message, key)
    except (ValueError, AttributeError):
        return "response was not an audio file"


def _decode_sse(body: bytes, key: str) -> bytes:
    fragments, done = [], False
    try:
        text = body.decode("utf-8")
        for frame in re.split(r"\r?\n\r?\n", text):
            data = "\n".join(line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:"))
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            if "error" in event or event.get("type") == "error":
                raise MingTTSError("Ming SSE error: " + _error_detail(data.encode(), key))
            if event.get("type") == "speech.audio.delta":
                fragments.append(base64.b64decode(event["audio"], validate=True))
            elif event.get("type") == "speech.audio.done":
                done = True
    except (UnicodeError, ValueError, KeyError, TypeError, binascii.Error) as exc:
        raise MingTTSError("Ming returned malformed SSE audio") from exc
    if not done or not fragments:
        raise MingTTSError("Ming SSE audio ended before a complete speech.audio.done event")
    return b"".join(fragments)


def synth(text: str, config: Mapping, *, sample_rate: int = 48000,
          api_key: str | None = None, timeout: float = 90,
          opener=None) -> bytes:
    payload = build_payload(text, config, sample_rate=sample_rate)
    key = api_key if api_key is not None else os.environ.get("MING_API_KEY", "")
    if not isinstance(key, str) or not key.strip():
        raise MingTTSError("Set MING_API_KEY before generating speech")
    key = key.strip()
    if any(char.isspace() for char in key):
        raise MingTTSError("MING_API_KEY must be a single token without whitespace")
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "audio/wav, text/event-stream"},
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=timeout) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    except urllib.error.HTTPError as exc:
        with exc:
            detail = _error_detail(exc.read(8192), key)
        raise MingTTSError(f"Ming HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise MingTTSError("Ming request failed: " + _safe_detail(exc, key)) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise MingTTSError("Ming audio response exceeded 100 MB")
    if content_type == "text/event-stream":
        audio = _decode_sse(body, key)
    elif content_type in ("audio/wav", "audio/x-wav", "audio/wave", "application/octet-stream"):
        audio = body
    else:
        raise MingTTSError("Ming returned unexpected content: " + _error_detail(body, key))
    validate_wav(audio, sample_rate=sample_rate)
    return audio
