"""Gate identity, coverage, effective review state, source evidence and PDF delivery."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from ocr_common import ROOT, read_json, validate, effective, atomic_json


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--skip-pdf', action='store_true')
    args = ap.parse_args()
    questions = read_json(ROOT / 'manifest.json')['questions']
    package_info = read_json(ROOT / 'extraction-report.json')['source_package']
    package = ROOT / 'source' / package_info['file']
    if hashlib.file_digest(package.open('rb'), 'sha256').hexdigest() != package_info['sha256']:
        raise ValueError('Original MarginNote package hash differs')
    with zipfile.ZipFile(package) as archive:
        if archive.testzip(): raise ValueError('Original package CRC failed')
    for field in ('qid', 'item_id', 'seq'):
        if len({q[field] for q in questions}) != len(questions): raise ValueError(f'Duplicate {field}')
    ids = {q['item_id'] for q in questions}
    files = {f.stem for f in (ROOT / 'json/ocr/question').glob('*.json')}
    if files != ids: raise ValueError('OCR coverage differs from manifest')
    fixes = read_json(ROOT / 'json/manual/fixups.json')
    if not set(fixes).issubset(ids): raise ValueError('Unknown manual correction ID')
    for item_id, patch in fixes.items():
        if not patch.get('_review'): raise ValueError(f'Missing review record: {item_id}')
        if patch.get('_evidence'):
            path = (ROOT / patch['_evidence']).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file(): raise ValueError('Missing local evidence')
    raw_counts, reviewed_counts = Counter(), Counter()
    for q in questions:
        raw = read_json(ROOT / 'json/ocr/question' / (q['item_id'] + '.json'))
        validate(raw, q)
        reviewed = effective(raw, fixes)
        validate(reviewed, q, check_status=True)
        raw_counts[raw['status']] += 1
        reviewed_counts[reviewed['status']] += 1
    report = {'status': 'passed', 'questions': len(questions), 'raw_status': dict(raw_counts),
              'effective_status': dict(reviewed_counts), 'manual_overlays': len(fixes),
              'source_package_hash_and_crc': 'passed',
              'uniqueness': ['qid', 'item_id', 'seq'], 'semantic_deduplication': 'not performed'}
    for script in ('verify.py', 'typeset/verify_books.py'):
        if args.skip_pdf and script.startswith('typeset'): continue
        subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT / 'tools' / script)], check=True, cwd=ROOT)
    if not args.skip_pdf:
        delivery = read_json(ROOT / 'output/pdf/交付校验报告.json')
        for edition, book in delivery['books'].items():
            pdf = ROOT / 'output/pdf' / book['file']
            if hashlib.file_digest(pdf.open('rb'), 'sha256').hexdigest() != book['sha256']:
                raise ValueError(f'Delivery PDF hash differs: {edition}')
        report['pdf_delivery'] = 'passed'
    atomic_json(ROOT / 'work/logs/project-check.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
