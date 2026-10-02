#!/usr/bin/env python3
"""Export a MarginNote question bank into a reproducible image work layer.

The main note on each leaf card is treated as the question anchor.  PNGs from
notes grouped into that card are preserved separately as related excerpts,
because a "with answers" notebook commonly stores solutions there.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import plistlib
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


PNG = b"\x89PNG\r\n\x1a\n"
ANSWER_HINT = re.compile(r"(?:【?答案】?|【?分析】?|(?:^|[\n（(])解[）)]?|证明|故选|应填)")


def connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def unpack_payload(blob: bytes | None) -> bytes | None:
    if not blob:
        return None
    try:
        archive = plistlib.loads(blob)
    except Exception:
        return None
    candidates: list[bytes] = []

    def collect(value):
        if isinstance(value, bytes):
            candidates.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)

    collect(archive.get("$objects", archive))
    if not candidates:
        return None
    return max(candidates, key=lambda value: (value.startswith(PNG), len(value)))


def media_ids(note: dict) -> list[str]:
    return [value for value in (note.get("ZMEDIA_LIST") or "").split("-") if value]


def coords_hash(note: dict) -> str:
    ids = media_ids(note)
    return ids[0] if ids else ""


def payload_position(note: dict, media: dict[str, bytes]) -> tuple[int, float]:
    for media_id in media_ids(note):
        payload = media.get(media_id, b"")
        if payload.lstrip().startswith((b"[", b"{")):
            try:
                data = json.loads(payload)
                first = data[0] if isinstance(data, list) and data else data
                rect = first.get("rect") or {}
                return int(first.get("page", 10**9)), float(rect.get("y", 0))
            except (ValueError, TypeError, AttributeError, KeyError):
                continue
    return 10**9, 0.0


def page_number(note: dict, media: dict[str, bytes]) -> int | None:
    page, _ = payload_position(note, media)
    return None if page == 10**9 else page


def load_database(db: sqlite3.Connection):
    notes = {row["ZNOTEID"]: dict(row) for row in db.execute("SELECT * FROM ZBOOKNOTE")}
    media: dict[str, bytes] = {}
    media_kinds = Counter()
    for row in db.execute("SELECT ZMD5, ZDATA FROM ZMEDIA"):
        payload = unpack_payload(row["ZDATA"])
        if payload is None:
            media_kinds["empty_or_unknown"] += 1
            continue
        media[row["ZMD5"]] = payload
        if payload.startswith(PNG):
            media_kinds["png"] += 1
        elif payload.lstrip().startswith((b"[", b"{")):
            media_kinds["json"] += 1
        else:
            media_kinds["other"] += 1

    books: dict[str, str] = {}
    columns = {row[1] for row in db.execute("PRAGMA table_info(ZBOOKCONFIG)")}
    title_column = next((name for name in ("ZBOOKNAME", "ZNAME", "ZTITLE") if name in columns), None)
    if title_column:
        for row in db.execute(f"SELECT ZMD5, {title_column} AS title FROM ZBOOKCONFIG"):
            books[row["ZMD5"]] = row["title"]
    return notes, media, books, dict(media_kinds)


def source_book(note: dict, books: dict[str, str]) -> str | None:
    book_md5 = note.get("ZBOOKMD5") or ""
    return books.get(book_md5[:32])


def build_forest(notes: dict[str, dict]):
    children = {
        note_id: [child for child in (note.get("ZMINDLINKS") or "").split("|") if child in notes]
        for note_id, note in notes.items()
    }
    child_ids = {child for values in children.values() for child in values}
    roots = [note_id for note_id in notes if note_id not in child_ids and children[note_id]]

    def descendants(note_id: str):
        yield note_id
        for child in children[note_id]:
            yield from descendants(child)

    roots_by_size = sorted(
        ((sum(1 for _ in descendants(root)), root) for root in roots),
        reverse=True,
    )
    if not roots_by_size:
        raise RuntimeError("No non-empty MarginNote mind-map root found")
    main_root = roots_by_size[0][1]
    return main_root, children, roots_by_size, descendants


def make_paths(root: str, children: dict[str, list[str]], notes: dict[str, dict]):
    paths: dict[str, list[str]] = {}
    sequences: dict[str, str] = {}

    def visit(note_id: str, names: list[str], indexes: list[int]):
        if not children[note_id]:
            prefix = ".".join(str(index) for index in indexes[:-1]) or "0"
            sequences[note_id] = f"{prefix}-{indexes[-1]:03d}"
            paths[note_id] = names
            return
        for index, child in enumerate(children[note_id], 1):
            title = (notes[child].get("ZNOTETITLE") or "").strip()
            visit(child, names + ([title] if children[child] else []), indexes + [index])

    visit(root, [], [])
    return paths, sequences


def note_pngs(note: dict, media: dict[str, bytes]) -> list[tuple[str, bytes]]:
    result: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    for media_id in media_ids(note):
        payload = media.get(media_id)
        if payload and payload.startswith(PNG) and media_id not in seen:
            seen.add(media_id)
            result.append((media_id, payload))
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_tree_json(root: str, children: dict[str, list[str]], notes: dict[str, dict], by_note: dict[str, dict]):
    def node(note_id: str):
        if note_id in by_note:
            question = by_note[note_id]
            return {
                "type": "question",
                "title": (notes[note_id].get("ZNOTETITLE") or "").strip() or None,
                "seq": question["seq"],
                "qid": question["qid"],
                "item_id": question["item_id"],
            }
        return {
            "type": "category",
            "title": (notes[note_id].get("ZNOTETITLE") or "").strip() or None,
            "children": [node(child) for child in children[note_id] if child in by_note or children[child]],
        }

    return node(root)


def write_outline(path: Path, root: str, children: dict[str, list[str]], notes: dict[str, dict], by_note: dict[str, dict]):
    def question_count(note_id: str) -> int:
        if note_id in by_note:
            return 1
        return sum(question_count(child) for child in children[note_id])

    root_title = (notes[root].get("ZNOTETITLE") or "题库").strip()
    lines = [f"# {root_title}", "", f"> 共 {question_count(root)} 道题；目录顺序来自 MarginNote 脑图树。", ""]

    def visit(note_id: str, depth: int):
        for child in children[note_id]:
            if child in by_note:
                question = by_note[child]
                lines.append(
                    f"{'  ' * depth}- `{question['seq']}` {question['source'] or '无出处'} · `{question['item_id']}`"
                )
            elif children[child]:
                title = (notes[child].get("ZNOTETITLE") or "（未命名）").strip()
                lines.append(f"{'  ' * depth}- **{title}**（{question_count(child)} 题）")
                visit(child, depth + 1)

    visit(root, 0)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_review(path: Path, manifest: dict):
    cards = []
    for question in manifest["questions"]:
        question_images = "".join(
            f'<img loading="lazy" src="{html.escape(item["path"])}">'
            for item in question["images"]["question"]
        ) or '<p class="missing">没有主卡题图</p>'
        related_images = "".join(
            f'<img loading="lazy" src="{html.escape(item["path"])}">'
            for item in question["images"]["related"]
        )
        related = (
            f'<details><summary>合并摘录候选（{len(question["images"]["related"])} 张）</summary>{related_images}</details>'
            if related_images else ""
        )
        cards.append(
            f'<article><header><b>{question["seq"]}</b><code>{question["item_id"]}</code>'
            f'<span>{html.escape(" / ".join(question["path"]))}</span>'
            f'<em>{html.escape(question["source"] or "无出处")}</em></header>'
            f'<section>{question_images}{related}</section></article>'
        )
    counts = manifest["counts"]
    doc = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>题库图片校对</title>
<style>
body{{font:14px system-ui;margin:0;background:#f3f5f7;color:#202124}}.bar{{position:sticky;top:0;z-index:2;padding:12px 18px;background:#17202a;color:#fff}}
article{{margin:14px;background:#fff;border:1px solid #d9dde3;border-radius:8px;overflow:hidden}}header{{display:flex;gap:12px;align-items:center;padding:10px 14px;background:#f8f9fa}}header span{{flex:1}}header em{{font-style:normal}}section{{padding:12px}}img{{display:block;max-width:100%;margin:0 auto 10px}}details{{margin-top:12px;border-top:1px dashed #bbb;padding-top:10px}}summary{{cursor:pointer;color:#7a3e00}}code{{color:#666}}.missing{{color:#a33}}@media(max-width:850px){{header span{{display:none}}}}
</style></head><body><div class="bar">{html.escape(manifest['root'])} · {counts['questions']} 题 · 题图 {counts['question_images']} · 合并摘录 {counts['related_images']}</div>{''.join(cards)}</body></html>'''
    path.write_text(doc, encoding="utf-8")


def export(source_db: Path, output: Path):
    if output.exists():
        raise RuntimeError(f"Output already exists; refusing to overwrite: {output}")
    staging = output.with_name(output.name + ".staging")
    if staging.exists():
        raise RuntimeError(f"Staging directory already exists: {staging}")

    for directory in (
        "img/question", "img/related", "img/answer",
        "json/ocr/question", "json/ocr/answer", "json/manual",
        "tex", "work/crops", "work/review", "work/logs",
    ):
        (staging / directory).mkdir(parents=True, exist_ok=True)

    db = connect(source_db)
    try:
        table_counts = {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("ZBOOKNOTE", "ZMEDIA", "ZBOOKCONFIG", "ZTOPIC")
        }
        notes, media, books, media_kinds = load_database(db)
    finally:
        db.close()

    root, children, roots_by_size, descendants = build_forest(notes)
    tree_ids = list(descendants(root))
    leaves = [note_id for note_id in tree_ids if not children[note_id] and len(coords_hash(notes[note_id])) >= 12]
    paths, sequences = make_paths(root, children, notes)

    reverse_groups: dict[str, list[str]] = defaultdict(list)
    for note_id, note in notes.items():
        if note.get("ZGROUPNOTEID"):
            reverse_groups[note["ZGROUPNOTEID"]].append(note_id)

    qid_counts = Counter(coords_hash(notes[note_id])[:12] for note_id in leaves)
    qid_seen = Counter()
    questions = []
    by_note: dict[str, dict] = {}
    for note_id in leaves:
        note = notes[note_id]
        full_hash = coords_hash(note)
        qid = full_hash[:12]
        qid_seen[qid] += 1
        item_id = qid if qid_counts[qid] == 1 else f"{qid}-dup{qid_seen[qid]}"

        grouped_notes = sorted(reverse_groups.get(note_id, []), key=lambda value: payload_position(notes[value], media))
        # In a "with answers" notebook the main card's ZMEDIA_LIST is often an
        # aggregate: it contains the question PNGs plus PNGs owned by grouped
        # solution excerpts.  The reliable question set is therefore the main
        # card set minus every grouped-note set.
        grouped_png_ids = {
            media_id
            for grouped_id in grouped_notes
            for media_id, _ in note_pngs(notes[grouped_id], media)
        }
        question_media = []
        for media_id, payload in note_pngs(note, media):
            if media_id in grouped_png_ids:
                continue
            index = len(question_media) + 1
            relative_path = f"img/question/{item_id}-{index:02d}.png"
            (staging / relative_path).write_bytes(payload)
            question_media.append({"path": relative_path, "media_md5": media_id, "note_id": note_id})

        related_media = []
        related_notes = []
        related_seen: set[str] = set()
        related_index = 0
        for grouped_id in grouped_notes:
            grouped_note = notes[grouped_id]
            raw_text = grouped_note.get("ZHIGHLIGHT_TEXT") or ""
            role_hint = "answer_candidate" if ANSWER_HINT.search(raw_text) else "related_excerpt"
            note_paths = []
            for media_id, payload in note_pngs(grouped_note, media):
                if media_id in related_seen:
                    continue
                related_seen.add(media_id)
                related_index += 1
                relative_path = f"img/related/{item_id}-{related_index:02d}.png"
                (staging / relative_path).write_bytes(payload)
                detail = {
                    "path": relative_path,
                    "media_md5": media_id,
                    "note_id": grouped_id,
                    "role_hint": role_hint,
                }
                related_media.append(detail)
                note_paths.append(relative_path)
            related_notes.append({
                "note_id": grouped_id,
                "title": (grouped_note.get("ZNOTETITLE") or "").strip() or None,
                "book": source_book(grouped_note, books),
                "page": page_number(grouped_note, media),
                "raw_text": raw_text,
                "role_hint": role_hint,
                "images": note_paths,
            })

        item = {
            "qid": qid,
            "item_id": item_id,
            "coords_hash": full_hash,
            "note_id": note_id,
            "seq": sequences[note_id],
            "path": paths[note_id],
            "source": (note.get("ZNOTETITLE") or "").strip() or None,
            "book": source_book(note, books),
            "page": page_number(note, media),
            "raw_text": note.get("ZHIGHLIGHT_TEXT") or "",
            "images": {"question": question_media, "related": related_media, "answer": []},
            "related_notes": related_notes,
        }
        questions.append(item)
        by_note[note_id] = item

    main_qids = {question["coords_hash"] for question in questions}
    other_roots = []
    for size, other_root in roots_by_size[1:]:
        other_leaves = [
            note_id for note_id in descendants(other_root)
            if not children[note_id] and len(coords_hash(notes[note_id])) >= 12
        ]
        other_qids = {coords_hash(notes[note_id]) for note_id in other_leaves}
        other_roots.append({
            "title": (notes[other_root].get("ZNOTETITLE") or "").strip() or None,
            "note_id": other_root,
            "nodes": size,
            "questions": len(other_leaves),
            "overlap_with_main": len(other_qids & main_qids),
            "unique_vs_main": len(other_qids - main_qids),
            "exported": False,
        })

    counts = {
        "questions": len(questions),
        "question_images": sum(len(question["images"]["question"]) for question in questions),
        "related_images": sum(len(question["images"]["related"]) for question in questions),
        "answer_images_classified": 0,
        "questions_without_question_image": sum(not question["images"]["question"] for question in questions),
        "questions_with_related_images": sum(bool(question["images"]["related"]) for question in questions),
        "duplicate_qid_occurrences": sum(value - 1 for value in qid_counts.values()),
    }
    source_stat = source_db.stat()
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    manifest = {
        "schema_version": 2,
        "generated_at": generated_at,
        "root": (notes[root].get("ZNOTETITLE") or "").strip(),
        "root_note_id": root,
        "source": {
            "file": source_db.name,
            "size_bytes": source_stat.st_size,
            "modified_at": datetime.fromtimestamp(source_stat.st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds"),
            "sha256": sha256_file(source_db),
        },
        "policy": {
            "question_images": "PNG payloads on each leaf/main card minus every PNG referenced by notes grouped into that card (main aggregate set - grouped excerpt set).",
            "related_images": "PNGs on notes whose ZGROUPNOTEID points to the main card; preserved separately for later answer/continuation classification.",
            "excluded_roots": "Non-main roots are excluded; overlap statistics are recorded in extraction-report.json.",
        },
        "counts": counts,
        "questions": questions,
    }
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": manifest["source"],
        "selected_root": {
            "title": manifest["root"], "note_id": root, "nodes": len(tree_ids), "questions": len(questions)
        },
        "excluded_roots": other_roots,
        "database_rows": table_counts,
        "unpacked_media": media_kinds,
        "counts": counts,
        "verification": {
            "all_question_files_are_png": True,
            "all_related_files_are_png": True,
            "manifest_question_file_count": counts["question_images"],
            "manifest_related_file_count": counts["related_images"],
        },
    }
    workflow = {
        "schema_version": 1,
        "source_manifest": "manifest.json",
        "stages": [
            {"id": "extract_question_images", "status": "complete", "output": "img/question"},
            {"id": "classify_related_images", "status": "pending", "input": "img/related", "output": "img/answer"},
            {"id": "ocr_questions", "status": "pending", "output": "json/ocr/question"},
            {"id": "ocr_answers", "status": "pending", "output": "json/ocr/answer"},
            {"id": "manual_fixes", "status": "pending", "output": "json/manual"},
            {"id": "typeset", "status": "pending", "output": "tex"},
        ],
    }

    (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (staging / "tree.json").write_text(
        json.dumps(build_tree_json(root, children, notes, by_note), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (staging / "extraction-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (staging / "workflow.json").write_text(json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outline(staging / "outline.md", root, children, notes, by_note)
    write_review(staging / "review.html", manifest)
    (staging / "README.md").write_text(
        f"# {manifest['root']} · 图片中间层\n\n"
        f"从 `{source_db.name}` 导出，共 {counts['questions']} 道题、{counts['question_images']} 张主卡题图。\n\n"
        "- `img/question/`：主卡聚合 PNG 减去合并摘录 PNG 后得到的题图；数据库原始字节，未重压。\n"
        "- `img/related/`：合并摘录图，通常是答案/解析，也可能是题干续页；尚未自动并入题图。\n"
        "- `img/answer/`：预留给复核后确认的答案图。\n"
        "- `manifest.json`：后续处理的唯一事实源；`tree.json` 保存目录树。\n"
        "- `extraction-report.json`：源文件指纹、排除重复根、计数与校验。\n"
        "- `workflow.json`：后续 OCR、人工修订与排版阶段状态。\n"
        "- `review.html`：题图校对页；合并摘录默认折叠。\n\n"
        "注意：带答案库的主卡媒体列表会聚合解析图，因此题图按“主卡 PNG − 合并摘录 PNG”提取。"
        "合并摘录没有直接改名为答案，避免把跨页题干误分类。\n",
        encoding="utf-8",
    )
    for directory in (
        "img/answer", "json/ocr/question", "json/ocr/answer", "json/manual",
        "tex", "work/crops", "work/review", "work/logs",
    ):
        (staging / directory / ".gitkeep").write_text("", encoding="utf-8")

    actual_question = len(list((staging / "img" / "question").glob("*.png")))
    actual_related = len(list((staging / "img" / "related").glob("*.png")))
    if actual_question != counts["question_images"] or actual_related != counts["related_images"]:
        raise RuntimeError(
            f"Image count mismatch: question {actual_question}/{counts['question_images']}, "
            f"related {actual_related}/{counts['related_images']}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(output)
    print(json.dumps(counts, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    export(args.source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
