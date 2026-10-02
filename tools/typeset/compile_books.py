"""Compile covers and both books twice, keeping full logs."""
import concurrent.futures
import subprocess
import shutil
import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

BANK = Path(__file__).resolve().parents[2]
OUT = BANK / 'tex'


def compile_file(path):
    is_cover = '-封皮' in path.stem
    engine = 'xelatex'
    job = ('cover-' if is_cover else 'book-') + ('blank' if '留空' in path.stem else 'compact')
    for number in (1, 2):
        result = subprocess.run([engine, '-jobname=' + job, '-interaction=nonstopmode', '-halt-on-error', '-file-line-error', path.name], cwd=OUT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (OUT / 'work' / f'{path.stem}-pass{number}.txt').write_bytes(result.stdout)
        if result.returncode:
            raise RuntimeError(result.stdout.decode('utf-8', errors='replace')[-4500:])
    shutil.copy2(OUT / (job + '.pdf'), path.with_suffix('.pdf'))
    print(f'Compiled: {path.name}', flush=True)


def main():
    (OUT / 'work').mkdir(exist_ok=True)
    paths = sorted(OUT.glob('澄潇宇大观题库-多元积分·*.tex'))
    covers = [p for p in paths if '-封皮' in p.stem]
    books = [p for p in paths if '-封皮' not in p.stem]
    for group in (covers, books):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            for future in [executor.submit(compile_file, path) for path in group]:
                future.result()
    subprocess.run([sys.executable, '-X', 'utf8', '-B', str(BANK / 'tools/typeset/verify_books.py')], check=True, cwd=BANK)
    delivery = BANK / 'output/pdf'
    delivery.mkdir(parents=True, exist_ok=True)
    report = json.loads((OUT / 'work/pdf-validation.json').read_text(encoding='utf-8'))
    for book in report['books'].values():
        shutil.copy2(OUT / book['file'], delivery / book['file'])
    report['generated_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    report['visual_review'] = {'status': 'not repeated by automated build; historical contact sheets retained under tex/work'}
    (delivery / '交付校验报告.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Verified both PDFs and updated output/pdf delivery copies')


if __name__ == '__main__':
    main()
