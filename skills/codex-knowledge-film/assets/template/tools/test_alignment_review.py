"""Offline regression fixtures; synthetic tones are not speech/model evidence."""
from array import array
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
import wave

import alignment_review as review


def tone(path, duration=1, rate=44100):
    count = round(duration * rate)
    samples = array('h', [int(5000 * math.sin(index * .031) + 900 * math.sin(index * index * .00001)) for index in range(count)])
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(rate); handle.writeframes(samples.tobytes())


def mark_reviewed(report):
    report['status'] = 'reviewed'
    report['review'] = {'reviewer': 'offline-test-fixture', 'method': 'Fixture transcript supplied by test; no real listening claimed',
                        'reviewedAt': '2026-11-03T08:00:00+08:00'}
    return report


def save(root, report):
    (root / 'reviews').mkdir(exist_ok=True)
    (root / 'reviews/alignment.json').write_text(json.dumps(report, ensure_ascii=False))


def fixture(root, texts):
    lines = []
    for index, text in enumerate(texts):
        path = root / f'line-{index}.wav'
        path.write_bytes(b'fixture-' + str(index).encode())
        lines.append({'id': f'line-{index}', 'text': text, 'audioFile': path.name})
    spec = {'audio': {'mode': 'import', 'alignmentReport': 'reviews/alignment.json'},
            'scenes': [{'id': 'one', 'lines': lines}]}
    raw = [{'id': line['id'], 'rawAsr': line['text']} for line in lines]
    return spec, raw


class TextBoundaryTests(unittest.TestCase):
    def test_actual_appeal_word_shift_fails_despite_high_similarity(self):
        rows = [
            {'id': 'line-09', 'text': '如果认为封错了，从官方帮助中心进入申诉。', 'rawAsr': '如果认为封错了，从官方帮助中心进入。'},
            {'id': 'line-15', 'text': '用被停用的原账户登录，填写官方表单。', 'rawAsr': '申诉用被停用的原账户登录填写官方表单。'}]
        result = review.analyze_rows(rows)
        self.assertEqual(result['status'], 'fail')
        self.assertTrue(all(row['similarityForDiagnosisOnly'] > .9 for row in result['lines']))
        self.assertEqual(result['lines'][0]['missing'], [{'text': '申诉', 'direction': 'end'}])
        self.assertEqual(result['lines'][1]['extra'], [{'text': '申诉', 'direction': 'start'}])
        self.assertIn({'from': 'line-09', 'to': 'line-15', 'text': '申诉', 'kind': 'tail-moved-to-next'}, result['adjacentIssues'])

    def test_merged_appeal_semantic_passage_passes(self):
        text = '如果认为封错了，从官方帮助中心进入申诉。用被停用的原账户登录，填写官方表单。'
        self.assertEqual(review.transcript_diffs(text, text.replace('。', '').replace('，', ''))['status'], 'pass')

    def test_missing_head_middle_tail_each_fail(self):
        for actual in ('进入申诉', '从官方申诉', '从官方进入'):
            self.assertEqual(review.transcript_diffs('从官方进入申诉', actual)['status'], 'fail')

    def test_extra_head_middle_tail_each_fail(self):
        for actual in ('申诉从官方进入', '从官方再次进入', '从官方进入申诉'):
            self.assertEqual(review.transcript_diffs('从官方进入', actual)['status'], 'fail')

    def test_adjacent_duplicate_detected(self):
        result = review.analyze_rows([{'id': 'a', 'text': '中心进入申诉', 'rawAsr': '中心进入申诉'},
                                      {'id': 'b', 'text': '填写表单', 'rawAsr': '申诉填写表单'}])
        self.assertEqual(result['status'], 'fail')
        self.assertTrue(any(row['kind'] == 'duplicate-boundary' for row in result['adjacentIssues']))

    def test_other_topic_arbitrary_length_and_punctuation(self):
        for count in (1, 3, 17):
            rows = [{'id': str(i), 'text': f'第{i}次，排队等候。', 'rawAsr': f'第{i}次排队等候'} for i in range(count)]
            self.assertEqual(review.analyze_rows(rows)['status'], 'pass')

    def test_homophone_keeps_raw_and_requires_evidence(self):
        raw = '从官方帮助中心进入申速'
        replacements = [{'kind': 'homophone', 'from': '速', 'to': '诉', 'reason': 'Independent ASR transcribed 申诉; listening confirmed this test scenario'}]
        self.assertEqual(review.transcript_diffs('从官方帮助中心进入申诉', raw, replacements)['status'], 'pass')
        self.assertEqual(raw, '从官方帮助中心进入申速')
        for bad in ({'from': '速', 'to': '诉'}, {'kind': 'homophone', 'from': '速', 'to': '诉', 'reason': ''},
                    {'kind': 'homophone', 'from': '申诉', 'to': '', 'reason': 'hide missing word'}):
            with self.assertRaises(ValueError):
                review.normalized_asr(raw, [bad])

    def test_normalizations_cannot_delete_add_or_replace_whole_sentence(self):
        for before, after in [('申诉', ''), ('申诉', '诉'), ('', '申诉'), ('填写表单', '进入申诉')]:
            with self.assertRaises(ValueError):
                review.normalized_asr('填写表单', [{'kind': 'homophone', 'from': before, 'to': after, 'reason': 'fixture'}])
        with self.assertRaises(ValueError):
            review.normalized_asr('甲乙丙丁', [{'kind': 'homophone', 'from': '甲', 'to': '一', 'reason': 'fixture'},
                                           {'kind': 'homophone', 'from': '乙', 'to': '二', 'reason': 'fixture'}])


class ManifestTests(unittest.TestCase):
    def test_candidate_is_pending_and_cannot_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); spec, raw = fixture(root, ['从官方进入申诉。'])
            candidate = review.make_candidate(root, spec, raw); save(root, candidate)
            self.assertEqual(candidate['status'], 'pending'); self.assertIsNone(candidate['review'])
            with self.assertRaisesRegex(ValueError, 'not explicitly reviewed'):
                review.validate_alignment(root, spec)

    def test_current_review_binds_arbitrary_final_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); spec, raw = fixture(root, ['排队消耗时间。', '窗口增加以后，等待变短。', '最后比较总时间。'])
            report = mark_reviewed(review.make_candidate(root, spec, raw)); save(root, report)
            self.assertEqual(review.validate_alignment(root, spec)['lineCount'], 3)

    def test_changed_text_audio_range_or_id_invalidates_review(self):
        for change in ('text', 'audio', 'id', 'context'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); spec, raw = fixture(root, ['第一句。', '第二句。'])
                save(root, mark_reviewed(review.make_candidate(root, spec, raw)))
                line = spec['scenes'][0]['lines'][0]
                if change == 'text': line['text'] = '改变后的句子。'
                elif change == 'audio': (root / line['audioFile']).write_bytes(b'changed')
                elif change == 'id': line['id'] = 'other-id'
                else: line['sourceContext'] = {'sourceFile': 'source.wav', 'sourceSha256': 'a'*64, 'startSeconds': 0, 'endSeconds': 1}
                with self.assertRaisesRegex(ValueError, 'stale'):
                    review.validate_alignment(root, spec)

    def test_missing_extra_reordered_rows_are_rejected_even_with_green_checks(self):
        for change in ('missing', 'extra', 'order'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); spec, raw = fixture(root, ['第一句。', '第二句。'])
                report = mark_reviewed(review.make_candidate(root, spec, raw))
                if change == 'missing': report['lines'].pop()
                elif change == 'extra': report['lines'].append(copy.deepcopy(report['lines'][0]))
                else: report['lines'].reverse()
                report['checks'] = {'status': 'pass'}; save(root, report)
                with self.assertRaises(ValueError): review.validate_alignment(root, spec)

    def test_green_status_never_overrides_bad_raw_asr(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); spec, raw = fixture(root, ['从官方帮助中心进入申诉。'])
            raw[0]['rawAsr'] = '从官方帮助中心进入'
            report = mark_reviewed(review.make_candidate(root, spec, raw)); report['checks'] = {'status': 'pass'}; save(root, report)
            with self.assertRaisesRegex(ValueError, 'boundary check failed'):
                review.validate_alignment(root, spec)

    def test_review_identity_method_timestamp_required(self):
        for change in ('reviewer', 'method', 'reviewedAt'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); spec, raw = fixture(root, ['第一句。'])
                report = mark_reviewed(review.make_candidate(root, spec, raw)); report['review'][change] = ''; save(root, report)
                with self.assertRaises(ValueError): review.validate_alignment(root, spec)

    def test_explicit_null_source_context_is_invalid_not_optional(self):
        with self.assertRaisesRegex(ValueError, "sourceContext requires"):
            review.verify_source_slice(".", {"id": "null-context", "sourceContext": None})
        self.assertEqual(review.verify_source_slice(".", {"id": "no-context"})["status"], "not-required")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); spec, raw = fixture(root, ["测试句子。"])
            spec["scenes"][0]["lines"][0]["sourceContext"] = None
            with self.assertRaisesRegex(ValueError, "sourceContext requires"):
                review.make_candidate(root, spec, raw)
        with self.assertRaisesRegex(ValueError, "alignmentReport"):
            review.validate_alignment(".", {"scenes": [{"lines": [{"sourceContext": None}]}]})

    def test_batch_without_review_report_fails(self):
        with self.assertRaisesRegex(ValueError, 'alignmentReport'):
            review.validate_alignment('.', {'scenes': [{'lines': [{'sourceContext': {}}]}]})
        self.assertEqual(review.validate_alignment('.', {'scenes': []})['status'], 'not-required')


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required for PCM evidence tests')
class SourcePCMTests(unittest.TestCase):
    def make(self, root, start=.1, end=.4):
        source = root / 'source.wav'; tone(source)
        context = {'sourceFile': 'source.wav', 'sourceSha256': review.sha256(source), 'startSeconds': start, 'endSeconds': end}
        cut = review.cut_source(root, context, 'cut.wav')
        return {'id': 'line-one', 'text': '排队等待。', 'audioFile': cut['audioFile'], 'sourceContext': context}

    def test_resample_then_sample_cut_has_exact_pcm_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); line = self.make(root)
            result = review.verify_source_slice(root, line)
            self.assertEqual(result['status'], 'verified'); self.assertEqual(result['sampleRate'], 48000)
            self.assertEqual(result['endSample'] - result['startSample'], 14400)

    def test_false_range_and_fabricated_same_length_slice_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); line = self.make(root)
            line['sourceContext'].update(startSeconds=.2, endSeconds=.5)
            with self.assertRaisesRegex(ValueError, 'PCM differs'): review.verify_source_slice(root, line)
            tone(root / 'cut.wav', duration=.3, rate=48000)
            with self.assertRaisesRegex(ValueError, 'PCM differs'): review.verify_source_slice(root, line)

    def test_changed_original_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); line = self.make(root)
            tone(root / 'source.wav', duration=.9)
            with self.assertRaisesRegex(ValueError, 'source audio hash changed'): review.verify_source_slice(root, line)

    def test_range_bounds_and_paths_are_not_metadata_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); line = self.make(root)
            for start, end in ((-.1, .2), (.2, .2), (0, 2), (False, .2), (float('nan'), .2)):
                line['sourceContext'].update(startSeconds=start, endSeconds=end)
                with self.assertRaises(ValueError): review.verify_source_slice(root, line)
            with self.assertRaises(ValueError): review.project_file(root, '../outside.wav')

    def test_contiguous_merge_returns_unique_final_mapping_and_requires_re_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); first = self.make(root, .1, .4)
            second = {'id': 'line-two', 'text': '增开窗口。', **review.cut_source(root, {**first['sourceContext'], 'startSeconds': .4, 'endSeconds': .8}, 'second.wav')}
            result = review.merge_contiguous(root, [first, second], 'merged-line', '排队等待。增开窗口。', 'merged.wav')
            self.assertEqual(result['replaces'], ['line-one', 'line-two'])
            self.assertEqual(review.verify_source_slice(root, result['line'])['status'], 'verified')
            spec = {'audio': {'alignmentReport': 'reviews/alignment.json'}, 'scenes': [{'lines': [result['line']]}]}
            candidate = review.make_candidate(root, spec, [{'id': 'merged-line', 'rawAsr': '排队等待增开窗口'}])
            save(root, mark_reviewed(candidate)); self.assertEqual(review.validate_alignment(root, spec)['lineCount'], 1)
            spec['scenes'][0]['lines'].append(second)
            with self.assertRaisesRegex(ValueError, 'stale'): review.validate_alignment(root, spec)

    def test_non_contiguous_merge_and_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); first = self.make(root)
            second = {'id': 'second', 'sourceContext': {**first['sourceContext'], 'startSeconds': .5, 'endSeconds': .8}}
            with self.assertRaisesRegex(ValueError, 'contiguous'):
                review.merge_contiguous(root, [first, second], 'merged', '合并内容', 'merged.wav')
            with self.assertRaisesRegex(ValueError, 'already exist'): review.cut_source(root, first['sourceContext'], 'cut.wav')


if __name__ == '__main__':
    unittest.main()
