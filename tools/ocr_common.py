"""Shared, repository-local OCR contracts. No external helper or credentials."""
from pathlib import Path
import json
import os
import re
import uuid
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BLOCKING_FLAGS = {'unclear_character', 'unclear_formula', 'possible_crop',
                  'image_order_uncertain', 'missing_context', 'option_parse_uncertain'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validator():
    return Draft202012Validator(read_json(ROOT / 'work/ocr-ai/output.schema.json'))


def validate(obj, question, check_status=False):
    validator().validate(obj)
    for name in ('qid', 'item_id'):
        if obj[name] != question[name]:
            raise ValueError(f'{name} differs for {question["item_id"]}')
    if [t['image'] for t in obj['image_transcriptions']] != [i['path'] for i in question['images']['question']]:
        raise ValueError('Input image order differs')
    if obj['question_type'] != 'choice' and obj['options']:
        raise ValueError('Non-choice question has options')
    if check_status and (obj['status'] != 'ok' or BLOCKING_FLAGS.intersection(obj['flags'])):
        raise ValueError(f'Unresolved OCR: {question["item_id"]}')
    def check_strings(value):
        if isinstance(value, str) and any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('Unexpected control character in OCR')
        if isinstance(value, dict):
            for v in value.values(): check_strings(v)
        if isinstance(value, list):
            for v in value: check_strings(v)
    check_strings(obj)


def effective(raw, patches):
    return {**raw, **{k: v for k, v in patches.get(raw['item_id'], {}).items() if not k.startswith('_')}}


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp.' + uuid.uuid4().hex)
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def safe_image(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / 'img/question') or not path.is_file():
        raise ValueError(f'Invalid question image: {relative}')
    return path


def prompt_parts(question):
    text = (ROOT / 'work/ocr-ai/prompt.md').read_text(encoding='utf-8')
    system, template = text.split('## 逐题用户消息模板', 1)
    fields = {'qid': question['qid'], 'item_id': question['item_id'], 'seq': question['seq']}
    for key in ('path', 'source', 'book', 'page', 'raw_text'):
        fields[key + '_json'] = json.dumps(question.get(key), ensure_ascii=False)
    fields['question_image_paths_json'] = json.dumps([i['path'] for i in question['images']['question']], ensure_ascii=False)
    for key, value in fields.items():
        template = template.replace('{{' + key + '}}', value)
    if re.search(r'\{\{\w+\}\}', template):
        raise ValueError('Unresolved prompt placeholder')
    system += '\n\nJSON Schema:\n' + json.dumps(read_json(ROOT / 'work/ocr-ai/output.schema.json'), ensure_ascii=False)
    return system, template


def parse_response(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


class RunLock:
    """Prevent concurrent writers; a crash leaves a lock for explicit inspection."""
    def __enter__(self):
        self.path = ROOT / 'runs/writer.lock'
        self.path.parent.mkdir(exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError('runs/writer.lock exists; inspect the running process before removing a stale lock')
        with os.fdopen(fd, 'w') as stream:
            stream.write(str(os.getpid()))
        return self

    def __exit__(self, *args):
        self.path.unlink(missing_ok=True)
