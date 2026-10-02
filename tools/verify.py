"""Validate manifest, tree, database provenance, and every exported PNG."""
import hashlib
import json
import sys
from pathlib import Path
from PIL import Image
import export_database as exporter


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    db_path = root / manifest['source']['file']
    assert exporter.sha256_file(db_path) == manifest['source']['sha256'], 'Database hash mismatch'
    db = exporter.connect(db_path)
    try:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        notes, media, books, kinds = exporter.load_database(db)
    finally:
        db.close()
    questions = manifest['questions']
    ids = [q['item_id'] for q in questions]
    assert len(ids) == len(set(ids)) == manifest['counts']['questions']
    tree = json.loads((root / 'tree.json').read_text(encoding='utf-8'))
    tree_ids = []
    def walk(node):
        if node['type'] == 'question':
            tree_ids.append(node['item_id'])
        else:
            for child in node['children']:
                walk(child)
    walk(tree)
    assert tree_ids == ids, 'Tree/manifest order mismatch'
    inventory = []
    roles = {}
    used_media = set()
    for role in ('question', 'related'):
        expected_paths = []
        for q in questions:
            for item in q['images'][role]:
                path = root / item['path']
                assert path.is_relative_to(root), 'Unsafe image path'
                payload = path.read_bytes()
                assert payload == media[item['media_md5']], f'Payload differs: {path}'
                with Image.open(path) as img:
                    width, height = img.size
                    assert img.format == 'PNG' and width > 0 and height > 0
                    img.verify()
                inventory.append({'path': item['path'], 'sha256': hashlib.sha256(payload).hexdigest(), 'width': width, 'height': height, 'bytes': len(payload)})
                expected_paths.append(path)
                used_media.add(item['media_md5'])
        actual_paths = set((root / 'img' / role).glob('*.png'))
        assert actual_paths == set(expected_paths), f'Image inventory mismatch: {role}'
        assert len(expected_paths) == manifest['counts'][role + '_images']
        roles[role] = len(expected_paths)
    all_png = {key for key, value in media.items() if value.startswith(exporter.PNG)}
    report = {
        'status': 'passed', 'database_integrity': 'ok', 'database_sha256_verified': True,
        'tree_order_verified': True, 'questions': len(questions), 'images': roles,
        'all_pngs_decode': True, 'all_image_bytes_match_database': True,
        'unique_exported_png_media': len(used_media), 'database_png_media': len(all_png),
        'unexported_png_media': sorted(all_png - used_media), 'image_inventory': inventory,
    }
    (root / 'work' / 'logs' / 'validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'image_inventory'}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    verify(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
