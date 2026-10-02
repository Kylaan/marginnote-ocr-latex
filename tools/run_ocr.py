"""OpenAI-compatible vision Chat Completions runner, local and resumable."""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
from urllib.parse import urlsplit
from ocr_common import (ROOT, BLOCKING_FLAGS, RunLock, read_json, validate,
                        atomic_json, safe_image, prompt_parts, parse_response)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, default=ROOT / 'config/ocr.json')
    ap.add_argument('--start', type=int, default=0, help='Zero-based manifest index')
    ap.add_argument('--limit', type=int, default=0, help='0 means all remaining')
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--max-attempts', type=int, default=3)
    ap.add_argument('--force', action='store_true', help='Overwrite raw OCR; manual overlays remain protected')
    ap.add_argument('--dry-run', action='store_true', help='Check tasks/images/prompts without API calls or writes')
    args = ap.parse_args()
    if args.start < 0 or args.limit < 0 or args.workers < 1 or args.max_attempts < 1:
        ap.error('Invalid index, worker count or retry count')
    questions = read_json(ROOT / 'manifest.json')['questions']
    for key in ('qid', 'item_id', 'seq'):
        if len({q[key] for q in questions}) != len(questions):
            raise ValueError(f'Duplicate {key}')
    end = args.start + args.limit if args.limit else len(questions)
    tasks = questions[args.start:end]
    pending = []
    skipped = 0
    for q in tasks:
        for im in q['images']['question']: safe_image(im['path'])
        prompt_parts(q)
        target = ROOT / 'json/ocr/question' / (q['item_id'] + '.json')
        if not args.force and target.exists():
            try:
                raw = read_json(target)
                validate(raw, q)
                if raw['status'] != 'failed':
                    skipped += 1
                    continue
            except Exception as exc:
                # Invalid existing results are retried, never treated as complete.
                print(f'Retry invalid result: {q["item_id"]} ({type(exc).__name__})')
        pending.append(q)
    print(json.dumps({'selected': len(tasks), 'skipped': skipped, 'pending': len(pending), 'dry_run': args.dry_run}))
    if args.dry_run or not pending:
        return 0
    if not args.config.is_file():
        ap.error('Copy config/ocr.example.json to config/ocr.json and set OCR_API_KEY')
    config = read_json(args.config)
    base = os.environ.get('OCR_BASE_URL', config.get('base_url', '')).rstrip('/')
    model = os.environ.get('OCR_MODEL', config.get('model', ''))
    proxy = os.environ.get('OCR_PROXY', config.get('proxy'))
    timeout = float(config.get('timeout_seconds', 900))
    key = os.environ.get('OCR_API_KEY')
    url = urlsplit(base)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        ap.error('Invalid base URL: no embedded credentials, query or fragment allowed')
    if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
        ap.error('Remote API connections require HTTPS')
    if not key or not model or model == 'YOUR_VISION_MODEL':
        ap.error('Set OCR_API_KEY and a vision-capable model')
    if proxy and (urlsplit(proxy).username or urlsplit(proxy).password):
        ap.error('Do not embed credentials in proxy URL')
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    logpath = ROOT / 'runs' / f'ocr-{timestamp}.jsonl'
    loglock = threading.Lock()
    def log(record):
        with loglock:
            with logpath.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    def process(q):
        system, user = prompt_parts(q)
        images = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(safe_image(im['path']).read_bytes()).decode('ascii')}} for im in q['images']['question']]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy} if proxy else {}))
        error = None
        for attempt in range(1, args.max_attempts + 1):
            retry = '' if attempt == 1 else '\n请重新输出满足 JSON Schema 的合法 JSON；保持输入 ID 与图像顺序，正确转义 LaTeX 反斜杠。'
            payload = {'model': model, 'temperature': 0, 'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': [{'type': 'text', 'text': user + retry}] + images}]}
            request = urllib.request.Request(base + '/chat/completions', data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
            try:
                with opener.open(request, timeout=timeout) as response:
                    result = json.load(response)
                obj = parse_response(result['choices'][0]['message']['content'])
                validate(obj, q)
                if obj['status'] == 'failed':
                    raise ValueError('Model reported failed')
                if obj['status'] == 'ok' and BLOCKING_FLAGS.intersection(obj['flags']):
                    obj['status'] = 'needs_review'
                validate(obj, q)
                atomic_json(ROOT / 'json/ocr/question' / (q['item_id'] + '.json'), obj)
                log({'item_id': q['item_id'], 'status': obj['status'], 'attempt': attempt})
                return obj['status']
            except Exception as exc:
                # Never record authorization headers, model raw output or response body.
                error = {'type': type(exc).__name__}
                if isinstance(exc, urllib.error.HTTPError): error['http_status'] = exc.code
                log({'item_id': q['item_id'], 'status': 'attempt_failed', 'attempt': attempt, **error})
                if attempt < args.max_attempts: time.sleep(min(5 * attempt, 30))
        log({'item_id': q['item_id'], 'status': 'failed', **error})
        return 'failed'
    with RunLock():
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(process, pending))
        summary = {'selected': len(tasks), 'skipped': skipped, 'processed': len(pending),
                   'counts': {s: results.count(s) for s in ('ok', 'needs_review', 'failed')}}
        atomic_json(ROOT / 'runs/ocr-progress.json', summary)
    print(json.dumps(summary))
    return int('failed' in results)


if __name__ == '__main__':
    raise SystemExit(main())
