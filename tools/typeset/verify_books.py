"""Check all item numbers, chapter bookmarks, page totals, and compiler logs."""
import hashlib
import json
import re
from pathlib import Path
import fitz
from jsonschema import Draft202012Validator

BANK = Path(__file__).resolve().parents[2]
TEX = BANK / 'tex'


def main():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    validator = Draft202012Validator(json.loads((BANK / 'work/ocr-ai/output.schema.json').read_text(encoding='utf-8')))
    expected = [q['seq'] for q in manifest['questions']]
    for q in manifest['questions']:
        data = json.loads((BANK / 'json/ocr/question' / (q['item_id'] + '.json')).read_text(encoding='utf-8'))
        validator.validate(data)
        assert data['qid'] == q['qid'] and data['item_id'] == q['item_id']
        assert [i['image'] for i in data['image_transcriptions']] == [i['path'] for i in q['images']['question']]
    books = {}
    for edition, job in [('无空版', 'book-compact'), ('留空版', 'book-blank')]:
        path = TEX / f'澄潇宇大观题库-多元积分·{edition}.pdf'
        log = (TEX / (job + '.log')).read_text(encoding='utf-8', errors='replace')
        for term in ('Missing character', 'Overfull', 'undefined', 'Undefined control sequence'):
            assert term not in log, f'{job}: {term}'
        with fitz.open(path) as pdf:
            text = '\n'.join(page.get_text() for page in pdf)
            found = re.findall(r'\d+(?:\.\d+)*-\d{3}', text)
            assert found == expected, 'Question numbers or order changed'
            assert not any(term in text for term in ('无法辨认', '题干缺失', '??', '\ufffd', '\uffff'))
            assert '澄潇宇大观' in pdf[0].get_text()
            assert edition in pdf[0].get_text()
            assert 'END OF COLLECTION' in pdf[-1].get_text()
            assert '目录' in pdf[2].get_text()
            chapters = [entry for entry in pdf.get_toc() if entry[0] == 1 and '章' in entry[1]]
            assert len(chapters) == 3
            footer = pdf[-2].get_text().replace(' ', '').replace('\n', '')
            body_pages = len(pdf) - 4
            assert f'第{body_pages}页，共{body_pages}页' in footer
            diagram_pages = []
            for seq in ('3.1.2.1.4-005', '3.1.2.2.2-005', '3.1.2.3-002'):
                page = next(page for page in pdf if seq in page.get_text())
                assert page.get_images(), f'Diagram separated from stem: {seq}'
                diagram_pages.append(page.number + 1)
            books[edition] = {
                'file': path.name, 'physical_pages': len(pdf), 'body_pages': body_pages,
                'questions': len(found), 'question_order_matches_manifest': True,
                'front_cover': 1, 'document_note': 2, 'contents': 3, 'back_cover': len(pdf),
                'chapter_bookmarks': chapters, 'diagram_pages': diagram_pages,
                'missing_characters': 0, 'overfull_boxes': 0, 'undefined_references': 0,
                'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
                'bytes': path.stat().st_size,
            }
    report = {'status': 'passed', 'ocr_schema_verified': len(expected), 'books': books}
    (TEX / 'work/pdf-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
