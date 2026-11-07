"""Offline provenance and alignment gates shared by preparation and final export.

An import receipt records observed evidence; it cannot authenticate a provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


class AudioGuardError(ValueError):
    pass


def canonical(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def project_file(root, value, label):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise AudioGuardError(label + ' must be a project-relative file')
    root = Path(root).resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise AudioGuardError(label + ' leaves the project') from None
    if not path.is_file():
        raise AudioGuardError(label + ' is missing')
    return path


def lines_for(spec):
    return [line for scene in spec['scenes'] for line in scene.get('lines', [])]


def line_binding(root, line):
    source = project_file(root, line.get('audioFile'), 'line.audioFile')
    result = {key: line[key] for key in ('id', 'text', 'audioFile')}
    result['audioSha256'] = digest(source)
    if 'sourceContext' in line:
        result['sourceContext'] = line['sourceContext']
    return result


def read_json(path, label):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (ValueError, UnicodeError) as error:
        raise AudioGuardError(label + ' is invalid JSON: ' + str(error)) from None


def _reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if re.search(r'(?i)(api.?key|access.?token|refresh.?token|cookie|authorization|password|secret)', key):
                raise AudioGuardError('Provenance receipts must not contain credentials')
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def provenance_receipt(root, spec, bindings):
    value = spec.get('audio', {}).get('provenanceFile')
    if value is None:
        return None
    path = project_file(root, value, 'audio.provenanceFile')
    receipt = read_json(path, 'Audio provenance receipt')
    _reject_secrets(receipt)
    if receipt.get('version') != 1:
        raise AudioGuardError('Audio provenance receipt needs version=1')
    for field in ('provider', 'backend', 'model', 'voice'):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            raise AudioGuardError('Audio provenance receipt needs ' + field)
    if not isinstance(receipt.get('parameters'), dict):
        raise AudioGuardError('Audio provenance receipt needs actual parameters (an object)')
    evidence = receipt.get('evidence')
    if not isinstance(evidence, dict) or any(not isinstance(evidence.get(key), str) or not evidence[key].strip()
                                           for key in ('kind', 'reference', 'observedAt', 'observer')):
        raise AudioGuardError('Audio provenance receipt needs explicit observed evidence')
    actual = receipt.get('lines')
    if not isinstance(actual, list) or len(actual) != len(bindings):
        raise AudioGuardError('Provenance receipt must map every final imported line exactly once')
    for row, expected in zip(actual, bindings):
        if not isinstance(row, dict) or canonical(row) != canonical(expected):
            raise AudioGuardError('Provenance receipt has stale line binding: ' + expected['id'])
    return {'file': value, 'sha256': digest(path), 'status': 'observed-source-evidence',
            'claimedProvider': receipt['provider'], 'claimedBackend': receipt['backend'],
            'claimedModel': receipt['model'], 'claimedVoice': receipt['voice'],
            'actualParameters': receipt['parameters'], 'modelVerified': False,
            'evidence': evidence}


def collect_inputs(root, spec, *, verify_pcm=True):
    """Resolve current immutable input bindings; no provider or ASR calls."""
    if spec.get('audio', {}).get('mode', 'silent') != 'import':
        return None
    lines = lines_for(spec)
    bindings = [line_binding(root, line) for line in lines]
    if verify_pcm:
        from alignment_review import verify_source_slice
        for line in lines:
            if 'sourceContext' in line:
                verify_source_slice(root, line)
    receipt = provenance_receipt(root, spec, bindings)
    review_path = spec.get('audio', {}).get('alignmentReport')
    alignment = None
    if review_path is not None:
        path = project_file(root, review_path, 'audio.alignmentReport')
        read_json(path, 'Alignment report')
        alignment = {'file': review_path, 'sha256': digest(path)}
    return {'version': 1, 'lines': bindings, 'provenance': receipt,
            'alignmentReport': alignment}


def import_identity(root, line, audio):
    binding = line_binding(root, line)
    # Receipt has a whole-film mapping: validate that once in collect_inputs;
    # each cache entry still includes its current content hash and claims.
    evidence = {}
    for field in ('provenanceFile', 'alignmentReport'):
        if field in audio:
            path = project_file(root, audio[field], 'audio.' + field)
            evidence[field] = {'file': audio[field], 'sha256': digest(path)}
    if 'provenanceFile' in audio:
        receipt = read_json(project_file(root, audio['provenanceFile'], 'audio.provenanceFile'), 'Audio provenance receipt')
        evidence['recordedGeneration'] = {key: receipt.get(key) for key in ('provider', 'backend', 'model', 'voice', 'parameters')}
    if 'sourceContext' in line:
        from alignment_review import verify_source_slice
        verify_source_slice(root, line)
    return {'transport': 'import', **binding, 'sourceSha256': binding['audioSha256'], 'evidence': evidence,
            'adapterVersion': 2, 'processingSampleRate': 48000}


def review_state(root, spec):
    if spec.get('audio', {}).get('mode', 'silent') != 'import':
        return {'status': 'not-required'}
    if not spec.get('audio', {}).get('alignmentReport') and not any('sourceContext' in line for line in lines_for(spec)):
        return {'status': 'unreviewed-import', 'contentReviewed': False}
    try:
        from alignment_review import validate_alignment
        return validate_alignment(root, spec, verify_pcm=False)
    except ValueError as error:
        return {'status': 'pending', 'contentReviewed': False, 'reason': str(error)}


def validate_export(root, spec, report):
    """Refuse stale input/review bindings even if a mix and ready flag exist."""
    root = Path(root).resolve()
    expected = lines_for(spec)
    built = report.get('lines')
    if not isinstance(built, list) or any(not isinstance(row, dict) for row in built) or [(row.get('id'), row.get('text')) for row in built] != [(line['id'], line['text']) for line in expected]:
        raise AudioGuardError('Build report must match every final script line in order')
    mode = spec.get('audio', {}).get('mode', 'silent')
    if mode == 'import':
        inputs = collect_inputs(root, spec, verify_pcm=True)
        if canonical(report.get('audioInputs')) != canonical(inputs):
            raise AudioGuardError('Audio input, source receipt, or alignment report changed; rerun preparation')
        for row, binding in zip(built, inputs['lines']):
            if row.get('sourceSha256') != binding['audioSha256'] or row.get('provenance', {}).get('sourceFile') != binding['audioFile']:
                raise AudioGuardError('Imported build provenance differs from final script: ' + binding['id'])
        if spec.get('audio', {}).get('alignmentReport') or any('sourceContext' in line for line in expected):
            from alignment_review import validate_alignment
            alignment = validate_alignment(root, spec, verify_pcm=True)
        else:
            alignment = {'status': 'unreviewed-import', 'contentReviewed': False}
    else:
        alignment = {'status': 'not-required'}
    if mode != 'silent':
        for row in built:
            for field, hash_field in (('sourcePath', 'sourceSha256'), ('preparedAudio', 'preparedSha256'), ('cacheReceipt', 'cacheReceiptSha256')):
                path = project_file(root, row.get(field), field)
                if digest(path) != row.get(hash_field):
                    raise AudioGuardError('Prepared source/cache changed: ' + row['id'] + ' ' + field)
    return {'status': 'pass', 'alignment': alignment,
            'provenance': (report.get('audioInputs') or {}).get('provenance')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        root = args.project.resolve()
        spec = read_json(root / 'content/film.json', 'Film spec')
        report = read_json(root / 'content/build-report.json', 'Build report')
        print(json.dumps(validate_export(root, spec, report), ensure_ascii=False))
        return 0
    except (ValueError, OSError) as error:
        print('Audio guard failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
