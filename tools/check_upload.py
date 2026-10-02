"""Scan exported text/archive entries for common credentials and LFS coverage."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
from ocr_common import ROOT, atomic_json, read_json

TEXT = {'.py', '.md', '.json', '.jsonl', '.txt', '.html', '.tex', '.yaml', '.yml', '.toml', '.env'}
LFS = {'.png', '.jpg', '.pdf', '.zip', '.marginpkg', '.marginnotes'}
TOKEN = re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b')
PASSWORD_PATTERN = re.compile(r'(?i)\bpassword\s*[:=]\s*["\x27]?([A-Za-z0-9_!@#$%^&*.-]{5,})')


def main():
    findings, large, checksums = [], [], []
    scanned = 0
    def scan(name, data):
        nonlocal scanned
        scanned += 1
        text = data.decode('utf-8', errors='replace')
        if TOKEN.search(text) or any(m.group(1) not in ('null', 'None', 'example') for m in PASSWORD_PATTERN.finditer(text)):
            findings.append(name)  # Never print matched secret values.
    attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
    for f in sorted(ROOT.rglob('*')):
        rel = f.relative_to(ROOT)
        if not f.is_file() or any(part in ('.git', '.venv', '__pycache__', 'runs') for part in rel.parts): continue
        if f.name in ('ocr.json', 'fonts.json') and rel.parts[0] == 'config': continue
        if f.suffix in TEXT: scan(rel.as_posix(), f.read_bytes())
        if f.suffix == '.zip':
            with zipfile.ZipFile(f) as z:
                if z.testzip(): raise ValueError(f'Archive CRC failed: {rel}')
                for entry in z.infolist():
                    if not entry.is_dir() and Path(entry.filename).suffix in TEXT:
                        scan(rel.as_posix() + '::' + entry.filename, z.read(entry))
        if f.stat().st_size > 100 * 1024 * 1024:
            if f.suffix not in LFS or ('*' + f.suffix + ' filter=lfs') not in attributes:
                raise ValueError(f'Missing LFS rule: {rel}')
            large.append({'path': rel.as_posix(), 'bytes': f.stat().st_size})
        if rel.parts[0] in ('source', 'archives') or (rel.parts[0] == 'output' and f.suffix == '.pdf'):
            checksums.append({'path': rel.as_posix(), 'bytes': f.stat().st_size,
                              'sha256': hashlib.file_digest(f.open('rb'), 'sha256').hexdigest()})
    if findings: raise ValueError('Credential-pattern matches in: ' + ', '.join(findings))
    for item in read_json(ROOT / 'docs/history/archive-inventory.json')['archives']:
        f = ROOT / item['path']
        if hashlib.file_digest(f.open('rb'), 'sha256').hexdigest() != item['sha256']:
            raise ValueError('Archive inventory hash mismatch')
    report = {'status': 'passed', 'text_entries_scanned': scanned,
              'credential_pattern_matches': 0, 'large_files_with_lfs_rules': large,
              'scope': 'Common token/password patterns in text and ZIP text entries; not a complete privacy assessment of binary databases.'}
    atomic_json(ROOT / 'work/logs/upload-check.json', report)
    atomic_json(ROOT / 'docs/history/data-checksums.json', {'files': checksums})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
