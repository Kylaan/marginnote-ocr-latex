"""Offline integration tests: mock HTTP, retries, shards and protected reviews."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'tools'))
import ocr_common as common


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for relative in ('tools/ocr_common.py', 'tools/run_ocr.py', 'tools/agent_tasks.py',
                         'work/ocr-ai/prompt.md', 'work/ocr-ai/output.schema.json'):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PROJECT / relative, target)
        self.questions = []
        for number in (1, 2):
            item = f'q{number}'
            paths = [f'img/question/{item}-{i}.png' for i in (1, 2)]
            for relative in paths:
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                Image.new('RGB', (2, 2), 'white').save(path)
            self.questions.append({'qid': item, 'item_id': item, 'seq': f'1-00{number}',
                'path': ['chapter'], 'source': 'fixture', 'book': 'fixture', 'page': 1,
                'raw_text': '', 'images': {'question': [{'path': p} for p in paths], 'related': []}})
        self.write('manifest.json', {'questions': self.questions})
        self.patch = {'q1': {'latex': 'reviewed formula', 'status': 'ok', '_review': 'fixture review'}}
        self.write('json/manual/fixups.json', self.patch)

    def write(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf-8')

    def result(self, q):
        return {'schema_version': 1, 'qid': q['qid'], 'item_id': q['item_id'],
            'status': 'ok', 'question_type': 'solution', 'latex': r'\frac{1}{2}',
            'options': [], 'image_transcriptions': [{'image': i['path'], 'latex': 'formula'} for i in q['images']['question']],
            'confidence': 0.95, 'flags': [], 'notes': ''}

    def cli(self, script, *args, **kwargs):
        return subprocess.run([sys.executable, '-X', 'utf8', '-B', str(self.root / 'tools' / script), *map(str, args)],
            cwd=self.root, capture_output=True, text=True, encoding='utf-8', **kwargs)

    def server(self, outputs):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                output = outputs[min(len(requests) - 1, len(outputs) - 1)]
                response = json.dumps({'choices': [{'message': {'content': output}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.write('config/ocr.json', {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'model': 'fixture', 'proxy': None})
        import os
        env = dict(os.environ)
        for key in ('OCR_BASE_URL', 'OCR_MODEL', 'OCR_PROXY'): env.pop(key, None)
        env['OCR_API_KEY'] = 'fixture-key-not-a-secret'
        return requests, env

    def test_retry_then_write_and_overlay_survives(self):
        good = self.result(self.questions[0])
        requests, env = self.server(['not JSON', json.dumps(good)])
        original = (self.root / 'json/manual/fixups.json').read_bytes()
        run = self.cli('run_ocr.py', '--limit', 1, '--force', '--max-attempts', 2, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(requests), 2)
        written = json.loads((self.root / 'json/ocr/question/q1.json').read_text())
        self.assertEqual(written, good)
        self.assertEqual(common.effective(written, self.patch)['latex'], 'reviewed formula')
        self.assertEqual(original, (self.root / 'json/manual/fixups.json').read_bytes())
        urls = requests[0]['messages'][1]['content'][1:]
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(i['image_url']['url'].startswith('data:image/png;base64,') for i in urls))
        self.assertNotIn('fixture-key-not-a-secret', '\n'.join(p.read_text() for p in (self.root / 'runs').glob('*.json*')))

    def test_wrong_identity_never_written(self):
        wrong = self.result(self.questions[0]); wrong['qid'] = 'wrong'
        previous = self.result(self.questions[0])
        self.write('json/ocr/question/q1.json', previous)
        _, env = self.server([json.dumps(wrong)])
        run = self.cli('run_ocr.py', '--limit', 1, '--force', '--max-attempts', 1, env=env)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads((self.root / 'json/ocr/question/q1.json').read_text()), previous)

    def test_resume_without_config_or_credentials(self):
        for q in self.questions: self.write(f'json/ocr/question/{q["item_id"]}.json', self.result(q))
        run = self.cli('run_ocr.py')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('"skipped": 2', run.stdout)
        self.assertFalse((self.root / 'runs').exists())

    def test_uncertain_result_is_downgraded(self):
        obj = self.result(self.questions[0]); obj['flags'] = ['unclear_formula']
        _, env = self.server([json.dumps(obj)])
        run = self.cli('run_ocr.py', '--limit', 1, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        written = json.loads((self.root / 'json/ocr/question/q1.json').read_text())
        self.assertEqual(written['status'], 'needs_review')

    def test_disjoint_plan_duplicate_rejection_and_merge(self):
        run = self.cli('agent_tasks.py', 'plan', '--shards', 2)
        self.assertEqual(run.returncode, 0, run.stderr)
        plan = self.root / 'runs/agent-plan/plan.json'
        assignments = json.loads(plan.read_text())['assignments']
        self.assertEqual([s['item_ids'] for s in assignments], [['q1'], ['q2']])
        for q in self.questions: self.write(f'candidates/{q["item_id"]}.json', self.result(q))
        self.write('duplicate/q1.json', self.result(self.questions[0]))
        run = self.cli('agent_tasks.py', 'merge', '--plan', plan, '--input', self.root / 'candidates', '--input', self.root / 'duplicate')
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((self.root / 'json/ocr/question').exists())
        run = self.cli('agent_tasks.py', 'merge', '--plan', plan, '--input', self.root / 'candidates')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(list((self.root / 'json/ocr/question').glob('*.json'))), 2)
        self.assertEqual(json.loads((self.root / 'json/manual/fixups.json').read_text()), self.patch)

    def test_image_order_contract(self):
        obj = self.result(self.questions[0]); obj['image_transcriptions'].reverse()
        old = common.ROOT
        common.ROOT = self.root
        try:
            with self.assertRaises(ValueError): common.validate(obj, self.questions[0])
        finally: common.ROOT = old


if __name__ == '__main__':
    unittest.main()
