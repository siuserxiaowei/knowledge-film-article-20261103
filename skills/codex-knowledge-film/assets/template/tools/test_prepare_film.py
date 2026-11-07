"""Offline tests. Tone WAVs are test fixtures, never claimed as Ming speech."""
import copy
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
import wave

import prepare_film as film


def spec(mode="silent", music=False):
    return {"version": 1, "id": "fixture-film", "title": "Fixture film", "width": 1920,
            "height": 1080, "fps": 30, "audio": {"mode": mode, "backend": "hf-space", "music": music,
            "model": film.MODEL, "voice": "灵小锋"}, "pacing": {"leadSeconds": .3, "tailSeconds": .45, "sceneGapSeconds": .3},
            "scenes": [{"id": "one", "kind": "comparison", "title": "Before and after", "visual": {"values": [2, 4]},
                        "lines": [{"id": "line-one", "text": "第一句。", "silentSeconds": 2.5},
                                  {"id": "line-two", "text": "第二句。", "silentSeconds": 3}]},
                       {"id": "close", "kind": "title", "title": "Complete", "durationSeconds": 2, "lines": []}]}


def wav(duration=.8, rate=48000):
    from array import array
    count = round(duration * rate)
    samples = array("h", [round(8000 * math.sin(2 * math.pi * 220 * index / rate)) for index in range(count)])
    output = io.BytesIO()
    with wave.open(output, "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(samples.tobytes())
    return output.getvalue()


def put_spec(root, value):
    path = Path(root) / "content/film.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))
    return path


class TimelineAndConfigurationTests(unittest.TestCase):
    def test_silent_film_uses_all_lines_and_has_no_fake_narration(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec()
            report = film.prepare(temp, value)
            result = json.loads((Path(temp) / "src/generated/timeline.json").read_text())
            self.assertTrue(result["ready"])
            self.assertFalse(result["narrated"])
            self.assertIsNone(result["audioSrc"])
            self.assertIsNone(report["model"])
            self.assertEqual(report["networkRequests"], 0)
            self.assertEqual(result["scenes"][0]["visual"], {"values": [2, 4]})
            self.assertEqual([line["text"] for line in result["captions"]], ["第一句。", "第二句。"])
            self.assertEqual(result["durationInFrames"], film.to_frame(result["durationSeconds"], 30))
            self.assertEqual(result["specHash"], film.spec_hash(value))

    def test_missing_silent_duration_is_explicitly_estimated(self):
        value = spec()
        del value["scenes"][0]["lines"][0]["silentSeconds"]
        with tempfile.TemporaryDirectory() as temp:
            report = film.prepare(temp, value)
            self.assertTrue(report["lines"][0]["estimated"])
            self.assertFalse(report["lines"][1]["estimated"])

    def test_frame_rounding_matches_nonnegative_javascript_round(self):
        self.assertEqual(film.to_frame(2.75, 30), 83)
        self.assertEqual(film.to_frame(.45, 30), 14)

    def test_spec_hash_is_key_order_independent_and_normalizes_integer_floats(self):
        value = spec()
        other = dict(reversed(list(value.items())))
        other["fps"] = 30.0
        self.assertEqual(film.spec_hash(value), film.spec_hash(other))
        other = copy.deepcopy(value)
        other["scenes"][0]["lines"][0]["text"] = "Changed"
        self.assertNotEqual(film.spec_hash(value), film.spec_hash(other))

    def test_dry_run_reads_no_credential_calls_no_service_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = put_spec(temp, spec())
            previous = path.read_bytes()
            with patch.object(film, "load_api_key", side_effect=AssertionError("credential read")), \
                 patch.object(film.ming_hf_space, "generate", side_effect=AssertionError("network")), \
                 patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(film.main(["--project", temp, "--mode", "ming", "--backend", "official", "--dry-run"]), 0)
            result = json.loads(stdout.getvalue())
            self.assertFalse(result["credentialsRead"])
            self.assertEqual(path.read_bytes(), previous)
            self.assertFalse((Path(temp) / "src").exists())
            self.assertFalse((Path(temp) / ".cache").exists())

    def test_explicit_mode_override_persists_and_hash_matches_output(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec()
            value["audio"]["mode"] = "ming"
            path = put_spec(temp, value)
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(film.main(["--project", temp, "--mode", "silent"]), 0)
            saved = json.loads(path.read_text())
            timeline = json.loads((Path(temp) / "src/generated/timeline.json").read_text())
            self.assertEqual(saved["audio"]["mode"], "silent")
            self.assertEqual(timeline["specHash"], film.spec_hash(saved))

    def test_sample_does_not_publish_or_replace_full_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec()
            value["scenes"][0]["lines"].extend([
                {"id": "line-three", "text": "第三句。", "silentSeconds": 2},
                {"id": "line-four", "text": "第四句。", "silentSeconds": 2}])
            full = Path(temp) / "src/generated/timeline.json"
            full.parent.mkdir(parents=True)
            full.write_text('{"ready":true,"existing":"full"}')
            previous = full.read_bytes()
            result = film.prepare(temp, value, sample=True)
            self.assertEqual(len(result["lines"]), 3)
            self.assertEqual(full.read_bytes(), previous)
            self.assertTrue((Path(temp) / "content/sample-build-report.json").is_file())

    def test_invalid_json_clears_old_ready_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path = put_spec(temp, spec())
            film.prepare(temp, spec())
            path.write_text("{broken")
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(film.main(["--project", temp]), 1)
            timeline = json.loads((Path(temp) / "src/generated/timeline.json").read_text())
            self.assertFalse(timeline["ready"])
            self.assertEqual(timeline["scenes"], [])

    def test_duplicate_line_ids_and_non_boolean_music_are_rejected(self):
        value = spec()
        value["scenes"][0]["lines"][1]["id"] = "line-one"
        with self.assertRaises(film.PrepareError):
            film.validate_spec(value)
        value = spec(); value["audio"]["music"] = "false"
        with self.assertRaises(film.PrepareError):
            film.validate_spec(value)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg/FFprobe required for actual media fixture tests")
class MediaAndTransportTests(unittest.TestCase):
    def test_import_uses_measured_audio_length_without_claiming_ming(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            value = spec("import")
            for index, line in enumerate(value["scenes"][0]["lines"]):
                path = root / f"voice-{index}.wav"; path.write_bytes(wav(.8 + index * .5, 44100))
                line["audioFile"] = path.name
            report = film.prepare(root, value)
            self.assertTrue(report["narrated"])
            self.assertIsNone(report["model"])
            self.assertEqual(report["transport"], "imported-unverified-provider")
            self.assertGreater(report["lines"][1]["durationSeconds"], report["lines"][0]["durationSeconds"])
            self.assertTrue(all(line["tempoRate"] == 1 for line in report["lines"]))
            self.assertTrue(all(line["durationBasis"] == "measured-audio" for line in report["lines"]))
            self.assertEqual(report["networkRequests"], 0)
            self.assertEqual(film.probe(root / "public/audio/mix.wav")["sampleRate"], 48000)

    def test_missing_import_invalidates_previous_success_and_never_calls_a_model(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            film.prepare(root, spec())
            value = spec("import")
            value["scenes"][0]["lines"][0]["audioFile"] = "missing.wav"
            network = Mock(side_effect=AssertionError("no model call"))
            with self.assertRaisesRegex(film.PrepareError, "missing"):
                film.prepare(root, value, hf_synth=network)
            network.assert_not_called()
            timeline = json.loads((root / "src/generated/timeline.json").read_text())
            self.assertFalse(timeline["ready"])
            self.assertIsNone(timeline["audioSrc"])

    def test_import_paths_cannot_escape_the_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"; root.mkdir()
            external = Path(temp) / "outside.wav"; external.write_bytes(wav())
            link = root / "link.wav"; link.symlink_to(external)
            for value in ("../outside.wav", "link.wav", str(external)):
                with self.subTest(path=value), self.assertRaises(film.PrepareError):
                    film.local_audio(root, value)

    def test_hf_mock_cache_is_reused_and_unsupported_controls_are_recorded(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec("ming")
            value["scenes"][0]["lines"] = value["scenes"][0]["lines"][:1]
            value["audio"].update({"instructions": "calm", "speed": .9})
            synth = Mock(return_value=(wav(.8, 44100), {"transport": "hf-space", "eventId": "fixture-not-live"}))
            first = film.prepare(temp, value, hf_synth=synth)
            synth.assert_called_once()
            self.assertEqual(first["ignoredParameters"], ["instructions", "speed"])
            self.assertEqual(first["networkRequests"], 1)
            self.assertEqual(first["model"], film.MODEL)
            blocked = Mock(side_effect=AssertionError("cache must avoid network"))
            second = film.prepare(temp, value, hf_synth=blocked)
            blocked.assert_not_called()
            self.assertEqual(second["networkRequests"], 0)
            self.assertTrue(second["lines"][0]["cacheReused"])

    def test_cache_context_includes_actual_backend_controls(self):
        value = spec("ming")
        line = value["scenes"][0]["lines"][0]
        original = film.source_identity(Path("."), line, value["audio"])[0]
        for field, option in (("voice", "灵小柔"), ("seed", 2026), ("cfg", 3), ("sigma", .4)):
            self.assertNotEqual(original, film.source_identity(Path("."), line, {**value["audio"], field: option})[0])
        self.assertNotEqual(original, film.source_identity(Path("."), {**line, "text": "别的文稿。"}, value["audio"])[0])
        config = {**value["audio"], "backend": "official"}
        official = film.source_identity(Path("."), line, config)[0]
        self.assertNotEqual(original, official)
        self.assertNotEqual(official, film.source_identity(Path("."), line, {**config, "instructions": "calm"})[0])

    def test_service_failure_redacts_key_never_retries_and_clears_ready(self):
        secret = "private-fixture-key-81273"
        with tempfile.TemporaryDirectory() as temp:
            value = spec("ming"); value["audio"]["backend"] = "official"
            synth = Mock(side_effect=RuntimeError("provider rejected Bearer " + secret))
            with patch.object(film, "load_api_key", return_value=secret), self.assertRaises(film.PrepareError) as caught:
                film.prepare(temp, value, official_synth=synth)
            synth.assert_called_once()
            self.assertNotIn(secret, str(caught.exception))
            self.assertNotIn(secret, (Path(temp) / "content/build-report.json").read_text())
            self.assertNotIn(secret, (Path(temp) / "src/generated/timeline.json").read_text())

    def test_later_quota_failure_keeps_first_source_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec("ming")
            synth = Mock(side_effect=[(wav(), {"transport": "hf-space", "eventId": "fixture"}), RuntimeError("quota exceeded")])
            with self.assertRaisesRegex(film.PrepareError, "quota exceeded"):
                film.prepare(temp, value, hf_synth=synth, clock=lambda: 10, sleeper=lambda _: None)
            self.assertEqual(synth.call_count, 2)
            self.assertEqual(len(list((Path(temp) / ".cache/audio").glob("*/source.wav"))), 1)
            report = json.loads((Path(temp) / "content/build-report.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(len(report["lines"]), 1)
            self.assertFalse(json.loads((Path(temp) / "src/generated/timeline.json").read_text())["ready"])

    def test_changed_cached_audio_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            value = spec("ming")
            value["scenes"][0]["lines"] = value["scenes"][0]["lines"][:1]
            film.prepare(temp, value, hf_synth=Mock(return_value=(wav(), {"transport": "hf-space"})))
            raw = next((Path(temp) / ".cache/audio").glob("*/source.wav"))
            raw.write_bytes(wav(.9))
            synth = Mock(side_effect=AssertionError("do not regenerate silently"))
            with self.assertRaisesRegex(film.PrepareError, "Cached source audio was changed"):
                film.prepare(temp, value, hf_synth=synth)
            synth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
