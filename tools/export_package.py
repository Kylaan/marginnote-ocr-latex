"""Rebuild an image work directory from a MarginNote package; never overwrite."""
import argparse
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
import export_database as exporter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package, output = args.package.resolve(), args.output.resolve()
    if output.exists():
        raise RuntimeError(f'Output already exists: {output}')
    with tempfile.TemporaryDirectory(prefix='marginpkg-') as tmp:
        with zipfile.ZipFile(package) as archive:
            bad = archive.testzip()
            if bad:
                raise RuntimeError(f'ZIP CRC failure: {bad}')
            members = [i for i in archive.infolist() if i.filename.endswith('.marginnotes')]
            if len(members) != 1:
                raise RuntimeError('Expected exactly one .marginnotes member')
            db_path = Path(tmp) / (package.stem + '.marginnotes')
            db_path.write_bytes(archive.read(members[0]))
        exporter.export(db_path, output)
        (output / 'source').mkdir()
        shutil.copy2(db_path, output / 'source' / db_path.name)
        package_info = {
            'file': package.name, 'size_bytes': package.stat().st_size,
            'sha256': exporter.sha256_file(package),
            'archive_member': members[0].filename, 'zip_crc_check': 'passed',
        }
        for name in ('manifest.json', 'extraction-report.json'):
            path = output / name
            data = json.loads(path.read_text(encoding='utf-8'))
            data['source']['file'] = 'source/' + db_path.name
            data['source_package'] = package_info
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tools_dir = output / 'tools'
    tools_dir.mkdir()
    for name in ('export_package.py', 'export_database.py', 'verify.py'):
        shutil.copy2(Path(__file__).parent / name, tools_dir / name)
    template_dir = Path(__file__).parent.parent / 'work' / 'ocr-ai'
    if template_dir.exists():
        shutil.copytree(template_dir, output / 'work' / 'ocr-ai')
    from verify import verify
    verify(output)


if __name__ == '__main__':
    main()
