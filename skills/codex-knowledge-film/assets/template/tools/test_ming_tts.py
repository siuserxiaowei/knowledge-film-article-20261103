"""Contract tests for Ming transport and cache identity; never contact the API."""
import base64
import copy
import io
import json
import unittest
import urllib.error
import wave
from unittest.mock import Mock

import ming_tts


def wav_bytes(rate=48000):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x80\x01" * 480)
    return stream.getvalue()


class Response(io.BytesIO):
    def __init__(self, body, content_type):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}


CONFIG = {"provider": "ming", "model": ming_tts.MODEL, "voice": "test-voice", "speed": 1.0}


class MingTTSTest(unittest.TestCase):
    def test_file_response_and_authentication(self):
        audio = wav_bytes()
        opener = Mock(return_value=Response(audio, "audio/wav; charset=binary"))
        result = ming_tts.synth("你好", CONFIG, api_key="private-token", opener=opener)
        self.assertEqual(result, audio)
        request = opener.call_args.args[0]
        self.assertEqual(request.full_url, ming_tts.ENDPOINT)
        self.assertEqual(request.get_header("Authorization"), "Bearer private-token")
        payload = json.loads(request.data)
        self.assertEqual(payload["sample_rate"], 48000)
        self.assertEqual(payload["response_format"], "wav")
        self.assertNotIn("stream_format", payload)
        self.assertNotIn("private-token", json.dumps(payload))

    def test_sse_audio_chunks_are_decoded_into_one_wav(self):
        audio = wav_bytes()
        events = [
            {"type": "speech.audio.delta", "audio": base64.b64encode(audio[:100]).decode()},
            {"type": "speech.audio.delta", "audio": base64.b64encode(audio[100:]).decode()},
            {"type": "speech.audio.done", "usage": {"total_tokens": 3}},
        ]
        stream = "\r\n\r\n".join("data: " + json.dumps(event) for event in events).encode()
        opener = Mock(return_value=Response(stream, "text/event-stream"))
        result = ming_tts.synth("你好", {**CONFIG, "stream_format": "sse"}, api_key="key", opener=opener)
        self.assertEqual(result, audio)

    def test_incomplete_sse_does_not_cache_partial_audio(self):
        stream = ('data: ' + json.dumps({"type": "speech.audio.delta", "audio": base64.b64encode(wav_bytes()).decode()}) + '\n\n').encode()
        opener = Mock(return_value=Response(stream, "text/event-stream"))
        with self.assertRaisesRegex(ming_tts.MingTTSError, "ended before"):
            ming_tts.synth("你好", CONFIG, api_key="key", opener=opener)

    def test_json_response_is_not_mistaken_for_audio(self):
        opener = Mock(return_value=Response(b'{"error":{"message":"quota exhausted"}}', "application/json"))
        with self.assertRaisesRegex(ming_tts.MingTTSError, "quota exhausted"):
            ming_tts.synth("你好", CONFIG, api_key="key", opener=opener)

    def test_http_failure_redacts_key_and_does_not_retry(self):
        key = "secret-123"
        error = urllib.error.HTTPError(ming_tts.ENDPOINT, 429, "Rate limited", {},
                                      io.BytesIO(json.dumps({"error": {"message": "Bearer " + key}}).encode()))
        opener = Mock(side_effect=error)
        with self.assertRaises(ming_tts.MingTTSError) as captured:
            ming_tts.synth("你好", CONFIG, api_key=key, opener=opener)
        self.assertNotIn(key, str(captured.exception))
        self.assertIn("429", str(captured.exception))
        opener.assert_called_once()

    def test_wrong_sample_rate_is_rejected(self):
        opener = Mock(return_value=Response(wav_bytes(44100), "audio/wav"))
        with self.assertRaisesRegex(ming_tts.MingTTSError, "44100 Hz"):
            ming_tts.synth("你好", CONFIG, api_key="key", opener=opener)

    def test_truncated_wav_is_rejected(self):
        with self.assertRaisesRegex(ming_tts.MingTTSError, "truncated"):
            ming_tts.validate_wav(wav_bytes()[:-20])

    def test_invalid_configuration_fails_before_network(self):
        opener = Mock()
        for text, config in [("", CONFIG), ("字" * 2049, CONFIG), ("你好", {**CONFIG, "speed": 5}),
                             ("你好", {**CONFIG, "stream_format": "audio"}),
                             ("你好", {**CONFIG, "references": [{"text": "reference", "audio": "bad"}]})]:
            with self.subTest(text=text[:10], config=config), self.assertRaises(ValueError):
                ming_tts.synth(text, config, api_key="key", opener=opener)
        opener.assert_not_called()

    def test_missing_key_fails_before_network(self):
        opener = Mock()
        with self.assertRaisesRegex(ming_tts.MingTTSError, "MING_API_KEY"):
            ming_tts.synth("你好", CONFIG, api_key="", opener=opener)
        opener.assert_not_called()

    def test_cache_changes_for_every_audible_setting(self):
        original = ming_tts.cache_key("你好", CONFIG)
        self.assertEqual(original, ming_tts.cache_key("你好", dict(reversed(list(CONFIG.items())))))
        for field, value in [("model", "future-model"), ("voice", "different-voice"), ("speed", 1.1),
                             ("instructions", "calm"), ("pitch", 1.1), ("volume", 1.1)]:
            with self.subTest(field=field):
                self.assertNotEqual(original, ming_tts.cache_key("你好", {**CONFIG, field: value}))
        self.assertNotEqual(original, ming_tts.cache_key("再见", CONFIG))
        self.assertNotEqual(original, ming_tts.cache_key("你好", CONFIG, sample_rate=44100))

    def test_clone_cache_uses_content_without_mutating_input(self):
        ref = {"audio": "data:audio/wav;base64," + base64.b64encode(wav_bytes()).decode(), "text": "参考音频"}
        config = {"provider": "ming", "references": [ref]}
        before = copy.deepcopy(config)
        original = ming_tts.cache_key("你好", config)
        self.assertEqual(config, before)
        self.assertNotEqual(original, ming_tts.cache_key("你好", {**config, "references": [{**ref, "text": "另一份转录"}]}))


if __name__ == "__main__":
    unittest.main()
