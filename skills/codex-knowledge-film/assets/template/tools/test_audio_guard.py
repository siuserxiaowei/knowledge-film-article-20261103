"""Provenance regression tests; synthetic chirps are never claimed as Ming speech."""
from array import array
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import audio_guard as guard
import prepare_film as film
from test_prepare_film import spec, put_spec, wav


def save(root, path, value):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def make_import(root, context=False):
    value = spec('import')
    value['scenes'][0]['lines'] = value['scenes'][0]['lines'][:1]
    line = value['scenes'][0]['lines'][0]
    line['audioFile'] = 'voice.wav'
    (root / 'voice.wav').write_bytes(wav())
    if context:
        data = array('h', [round(7000 * math.sin(2 * math.pi * (170 * i / 48000 + 110 * (i / 48000) ** 2))) for i in range(96000)])
        with wave.open(str(root / 'source.wav'), 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(48000); handle.writeframes(data.tobytes())
        with wave.open(str(root / 'voice.wav'), 'wb') as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(48000); handle.writeframes(data[4800:38400].tobytes())
        line['sourceContext'] = {'sourceFile': 'source.wav', 'sourceSha256': guard.digest(root / 'source.wav'),
                                 'startSeconds': .1, 'endSeconds': .8}
    return value, line


def receipt(root, value):
    data = {'version': 1, 'provider': 'ming', 'backend': 'hf-space-ui', 'model': 'inclusionAI/Ming-3.0-tts-0.5B',
            'voice': '灵小锋', 'parameters': {'seed': 1895, 'cfg': 2, 'sigma': .25},
            'evidence': {'kind': 'observed-ui-generation', 'reference': 'https://example.test/generation/fixture',
                         'observedAt': '2026-11-03T10:00:00+08:00', 'observer': 'fixture-observer'},
            'lines': [guard.line_binding(root, line) for line in guard.lines_for(value)]}
    value['audio']['provenanceFile'] = 'reviews/provenance.json'
    save(root, 'reviews/provenance.json', data)
    return data


def review(root, value, status='reviewed'):
    import alignment_review
    bindings = [guard.line_binding(root, line) for line in guard.lines_for(value)]
    data = {'version': 1, 'status': status, 'bindingSha256': alignment_review.binding_hash(bindings),
            'review': {'reviewer': 'fixture-reviewer', 'method': 'listened to each clip', 'reviewedAt': '2026-11-03T10:00:00+08:00'},
            'lines': [{**guard.line_binding(root, line), 'rawAsr': line['text'], 'normalizations': []}
                      for line in guard.lines_for(value)]}
    value['audio']['alignmentReport'] = 'reviews/alignment.json'
    save(root, 'reviews/alignment.json', data)
    return data


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
class SourceGuardTests(unittest.TestCase):
    def test_plain_unknown_import_stays_unverified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root)
            report = film.prepare(root, value)
            self.assertIsNone(report['model'])
            self.assertFalse(report['lines'][0]['provenance']['modelVerified'])
            self.assertEqual(report['reviewState']['provenance'], 'unverified-import')
            self.assertEqual(guard.validate_export(root, value, report)['alignment']['status'], 'unreviewed-import')

    def test_receipt_is_bound_without_claiming_provider_authentication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root)
            receipt(root, value)
            report = film.prepare(root, value)
            self.assertFalse(report['audioInputs']['provenance']['modelVerified'])
            self.assertEqual(report['reviewState']['provenance'], 'observed-source-evidence')
            self.assertIsNone(report['model'])
            guard.validate_export(root, value, report)
            save(root, 'reviews/provenance.json', {**json.loads((root / 'reviews/provenance.json').read_text()), 'voice': 'Different voice'})
            with self.assertRaisesRegex(ValueError, 'changed'):
                guard.validate_export(root, value, report)

    def test_missing_receipt_and_stale_final_mapping_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root)
            data = receipt(root, value)
            data['lines'].append(copy.deepcopy(data['lines'][0]))
            save(root, 'reviews/provenance.json', data)
            with self.assertRaisesRegex(ValueError, 'every final'):
                film.prepare(root, value)
            (root / 'reviews/provenance.json').unlink()
            with self.assertRaisesRegex(ValueError, 'missing'):
                film.prepare(root, value)

    def test_receipt_must_match_text_audio_and_context(self):
        for change in ('text', 'audioSha256', 'sourceContext'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); value, line = make_import(root, context=True)
                data = receipt(root, value)
                data['lines'][0][change] = 'stale'
                save(root, 'reviews/provenance.json', data)
                with self.assertRaisesRegex(ValueError, 'stale line'):
                    guard.collect_inputs(root, value)

    def test_receipt_with_credentials_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root)
            data = receipt(root, value); data['parameters']['apiKey'] = 'fixture-never-log'
            save(root, 'reviews/provenance.json', data)
            with self.assertRaisesRegex(ValueError, 'credentials'):
                guard.collect_inputs(root, value)

    def test_source_change_and_forged_slice_are_rejected(self):
        for target in ('source.wav', 'voice.wav'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); value, line = make_import(root, context=True)
                guard.collect_inputs(root, value)
                (root / target).write_bytes(wav(.7 if target == 'voice.wav' else 2))
                with self.assertRaises(ValueError):
                    guard.collect_inputs(root, value)

    def test_changed_range_and_out_of_bounds_are_rejected(self):
        for start, end in ((.2, .9), (-1, .8), (.1, 3), (.8, .1), (float('nan'), .8)):
            with self.subTest(bounds=(start, end)), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); value, line = make_import(root, context=True)
                line['sourceContext'].update(startSeconds=start, endSeconds=end)
                with self.assertRaises(ValueError):
                    guard.collect_inputs(root, value)

    def test_source_and_receipt_paths_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'project'; root.mkdir()
            outside = Path(temp) / 'outside.wav'; outside.write_bytes(wav(2))
            value, line = make_import(root, context=True)
            line['sourceContext']['sourceFile'] = '../outside.wav'
            with self.assertRaises(ValueError):
                guard.collect_inputs(root, value)
            value['scenes'][0]['lines'][0].pop('sourceContext')
            value['audio']['provenanceFile'] = '../outside.wav'
            with self.assertRaises(ValueError):
                guard.collect_inputs(root, value)

    def test_batch_preview_can_be_pending_but_export_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root, context=True)
            report = film.prepare(root, value)
            self.assertEqual(report['status'], 'complete')
            self.assertEqual(report['reviewState']['alignment']['status'], 'pending')
            with self.assertRaises(ValueError):
                guard.validate_export(root, value, report)
            review(root, value)
            reviewed = film.prepare(root, value)
            self.assertEqual(reviewed['reviewState']['alignment']['status'], 'reviewed')
            guard.validate_export(root, value, reviewed)

    def test_changed_review_requires_reprepare_even_if_still_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root, context=True)
            data = review(root, value)
            report = film.prepare(root, value)
            data['review']['method'] = 'listened again'
            save(root, 'reviews/alignment.json', data)
            with self.assertRaisesRegex(ValueError, 'changed'):
                guard.validate_export(root, value, report)

    def test_cache_key_binds_receipt_review_source_and_text(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root, context=True)
            data = receipt(root, value); reviewed = review(root, value)
            first = film.source_identity(root, line, value['audio'])[0]
            data['parameters']['seed'] = 33; save(root, 'reviews/provenance.json', data)
            self.assertNotEqual(first, film.source_identity(root, line, value['audio'])[0])
            first = film.source_identity(root, line, value['audio'])[0]
            reviewed['review']['method'] = 'listened again'; save(root, 'reviews/alignment.json', reviewed)
            self.assertNotEqual(first, film.source_identity(root, line, value['audio'])[0])
            first = film.source_identity(root, line, value['audio'])[0]
            line['text'] = '另一段内容。'
            self.assertNotEqual(first, film.source_identity(root, line, value['audio'])[0])

    def test_deleted_report_line_and_changed_prepared_cache_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); value, line = make_import(root)
            report = film.prepare(root, value)
            shorter = copy.deepcopy(report); shorter['lines'] = []
            with self.assertRaisesRegex(ValueError, 'every final script line'):
                guard.validate_export(root, value, shorter)
            prepared = root / report['lines'][0]['preparedAudio']; prepared.write_bytes(wav(.9))
            with self.assertRaisesRegex(ValueError, 'cache changed'):
                guard.validate_export(root, value, report)


if __name__ == '__main__':
    unittest.main()
