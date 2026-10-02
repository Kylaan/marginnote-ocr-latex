#!/usr/bin/env python3
"""Build the selected 770-question bank into chapter TeX and two full books.

Inputs:
  【独立】-严选题/大观严选题（数学一·带答案）/manifest.json
  【独立】-严选题/大观严选题（数学一·带答案）/产物/json/ocr/question/*.json
  交付/源文件/帕拉迪宇大观做题本-高等数学·无空版*.tex

Outputs are written under the bank's tex/ directory.  Only the structured OCR
``latex`` and ``options`` fields enter the body; per-image transcriptions are
never typeset because many source image bundles contain solution pages.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

import build_tex as legacy
import crop_figs


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "【独立】-严选题" / "大观严选题（数学一·带答案）"
PRODUCT = BANK / "产物"
OUT = BANK / "tex"
SOURCE_TEX = ROOT / "交付" / "源文件"

SOLID_TEMPLATE = SOURCE_TEX / "帕拉迪宇大观做题本-高等数学·无空版.tex"
BLANK_TEMPLATE = SOURCE_TEX / "帕拉迪宇大观做题本-高等数学·留空版.tex"
COVER_TEMPLATE = SOURCE_TEX / "帕拉迪宇大观做题本-高等数学·无空版-封皮.tex"

BASE_NAME = "澄潇宇大观严选题-高等数学"
LEGACY_BASE_NAMES = ("帕拉迪宇大观严选题-高等数学",)
CHAPTERS = [
    ("函数极限连续", "第一章 函数·极限·连续", "ch01-函数极限连续"),
    ("一元微分", "第二章 一元微分", "ch02-一元微分"),
    ("一元积分", "第三章 一元积分", "ch03-一元积分"),
    ("多元微分", "第四章 多元微分", "ch04-多元微分"),
    ("二重积分", "第五章 二重积分", "ch05-二重积分"),
    ("微分方程", "第六章 微分方程", "ch06-微分方程"),
    ("级数", "第七章 级数", "ch07-级数"),
]

ANSWER_MARK = re.compile(r"【\s*(?:答案|解|分析)\s*】|(?:答案|分析)[：:]|^\s*解[：:]", re.M)

# A fraction-heavy answer block in this question looks like a diagram to the
# generic connected-component detector.  Keep only the rod sketch on the right.
FIGURE_OVERRIDES = {
    "9e5b293a5479": (730, 118, 1120, 285),
}

# A few OCR-perfect stems contain formulas that are wider than the printable
# measure.  These overrides preserve the mathematics while introducing
# deliberate display breaks, so neither edition clips content at the right
# margin.
STEM_LAYOUT_OVERRIDES = {
    "e22e51b8ad1d": r"""【例 6.9】(2010，数二)计算二重积分
\[
I=\iint_{D}r^{2}\sin\theta\sqrt{1-r^{2}\cos 2\theta}\,drd\theta,
\]
其中
\[
D=\left\{(r,\theta)\left|0\leq r\leq\sec\theta,\ 0\leq\theta\leq\frac{\pi}{4}\right.\right\}.
\]""",
    "49841dd89829": r"""【例 6.17】(2014，数二、三)计算二重积分
\[
\iint_D\frac{x\sin(\pi\sqrt{x^2+y^2})}{x+y}\,dxdy,
\]
其中
\[
D=\left\{(x,y)\mid 1\leq x^2+y^2\leq 4,\ x\geq 0,\ y\geq 0\right\}.
\]""",
    "9b55eb9f2969": r"""331 在如下四个级数
\[
\begin{aligned}
\text{\cnum{1} }&\sum_{n=1}^{\infty}(-1)^{n-1}\frac{\ln(n+1)}{n}, &
\text{\cnum{2} }&\sum_{n=1}^{\infty}(-1)^{n-1}\frac{n}{2^n},\\
\text{\cnum{3} }&\sum_{n=2}^{\infty}\frac{(-1)^{n-1}}{\sqrt n-(-1)^n}, &
\text{\cnum{4} }&\sum_{n=1}^{\infty}\sin\left(n\pi+\frac{1}{\sqrt n}\right)
\end{aligned}
\]
中，条件收敛的级数是""",
    "bf976e1411ab": r"""设
\[
f(x)=\begin{cases}
x, & 0\leqslant x\leqslant\dfrac12,\\
2-2x, & \dfrac12<x<1,
\end{cases}
\qquad
S(x)=\dfrac{a_0}{2}+\sum_{n=1}^{\infty}a_n\cos n\pi x,
\]
$-\infty<x<+\infty$，其中
\[
a_n=2\int_0^1 f(x)\cos n\pi x\,dx\quad(n=0,1,2,\cdots),
\]
则 $S\left(-\dfrac52\right)$ 等于（ ）""",
}


def load_inputs():
    manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
    ocr = {}
    for path in (PRODUCT / "json" / "ocr" / "question").glob("*.json"):
        item = json.loads(path.read_text(encoding="utf-8"))
        ocr[item["item_id"]] = item
    missing = [q["item_id"] for q in manifest["questions"] if q["item_id"] not in ocr]
    if missing:
        raise RuntimeError(f"Missing OCR for {len(missing)} questions: {missing[:10]}")
    return manifest, ocr


def chapter_key(title: str) -> tuple[str, str]:
    for index, (source_title, _, filename) in enumerate(CHAPTERS, 1):
        if source_title == title:
            return f"ch{index:02d}", filename
    raise KeyError(title)


def clean_source(source: str | None) -> str:
    return legacy.meta(source or "")


def normalize_inline_math_delimiters(text: str) -> str:
    r"""Convert ``\(...\)`` to dollars and drop it when already inside ``$...$``.

    One OCR item wrapped a complete expression in dollars while retaining an
    inner pair of LaTeX inline delimiters.  XeLaTeX rejects that nesting with
    ``Bad math environment delimiter``.  Normalizing before the legacy cleanup
    also prevents options written as ``\(...\)`` from being wrapped a second
    time by ``wrap_option``.
    """
    out: list[str] = []
    in_dollar = False
    i = 0
    while i < len(text):
        if text[i] == "$" and (i == 0 or text[i - 1] != "\\"):
            in_dollar = not in_dollar
            out.append(text[i])
            i += 1
            continue
        token = text[i:i + 2]
        if token in (r"\(", r"\)"):
            if not in_dollar:
                out.append("$")
            i += 2
            continue
        out.append(text[i])
        i += 1
    normalized = "".join(out)
    # OCR occasionally appends a lone dollar after a fill-in underline.  The
    # corpus audit currently finds one such item; removing the final unmatched
    # delimiter is safer than letting it put the remainder of the chapter in
    # math mode.
    if normalized.count("$") % 2:
        last = normalized.rfind("$")
        normalized = normalized[:last] + normalized[last + 1:]
    return normalized


def render_question_text(question: dict, ocr: dict, figure_paths: list[str], warnings: list[str]) -> str:
    options = ocr.get("options") or []
    stem_source = STEM_LAYOUT_OVERRIDES.get(question["item_id"], ocr.get("latex") or "")
    stem_source = normalize_inline_math_delimiters(stem_source)
    stem = legacy.clean_stem(stem_source, bool(options), ocr.get("question_type", ""))
    if not stem:
        warnings.append(f"{question['item_id']}: empty stem")
        stem = r"\text{[题干缺失]}"
    residue = legacy.MATH_ONLY.search(legacy.outside_math(stem))
    if residue:
        warnings.append(f"{question['item_id']}: math command outside math: {residue.group(0)!r}")
    if legacy.brace_balance(stem):
        warnings.append(f"{question['item_id']}: unbalanced stem braces")

    parts = [stem]
    if options:
        cols = legacy.option_columns(options)
        width = {4: "0.235", 2: "0.48", 1: "0.97"}[cols]
        rows = []
        for start in range(0, len(options), cols):
            cells = []
            for option in options[start:start + cols]:
                option_source = normalize_inline_math_delimiters(option.get("latex") or "")
                text = legacy.render_option(option_source)
                if legacy.brace_balance(text):
                    warnings.append(f"{question['item_id']}: unbalanced option {option.get('label')}")
                cells.append(f"\\opt{{{option.get('label', '?')}}}{{{text}}}")
            rows.append("\\hfill".join(cells))
        parts.append(
            f"\\begin{{opts}}{{{width}}}\n" + "\\\\[0.3ex]\n".join(rows) + "\n\\end{opts}"
        )
    if figure_paths:
        figures = "\n".join(f"\\qfig{{{path}}}" for path in figure_paths)
        parts.append(f"\\begin{{figblock}}\n{figures}\n\\end{{figblock}}")
    return "\n".join(parts)


def candidate_question_images(question: dict, ocr: dict) -> list[tuple[Path, str]]:
    """Choose images likely to hold the actual question diagram, not solution art."""
    transcriptions = {
        item.get("image"): item.get("latex") or ""
        for item in ocr.get("image_transcriptions", []) if isinstance(item, dict)
    }
    candidates = []
    for image in question["images"]["question"]:
        rel = image["path"]
        text = transcriptions.get(rel, "")
        if ANSWER_MARK.search(text):
            continue
        if legacy.FIGURE_HINT.search(text) or rel == question["images"]["question"][-1]["path"]:
            candidates.append((BANK / rel, rel))
    if not candidates:
        image = question["images"]["question"][-1]
        candidates = [(BANK / image["path"], image["path"])]
    return candidates


def make_figures(manifest: dict, ocr_map: dict) -> tuple[dict[str, list[str]], dict]:
    fig_dir = OUT / "assets" / "fig"
    preview_dir = OUT / "work"
    fig_dir.mkdir(parents=True, exist_ok=True)
    preview_dir.mkdir(parents=True, exist_ok=True)

    figure_map: dict[str, list[str]] = {}
    report_items = []
    preview_panels = []
    for question in manifest["questions"]:
        ocr = ocr_map[question["item_id"]]
        if not legacy.has_figure(ocr):
            continue
        produced = []
        for source_path, source_rel in candidate_question_images(question, ocr):
            image = Image.open(source_path)
            box = FIGURE_OVERRIDES.get(question["item_id"]) or crop_figs.detect(image)
            index = len(produced) + 1
            filename = f"{question['item_id']}-{index:02d}.png"
            target = fig_dir / filename
            if box:
                image.crop(box).save(target)
            else:
                image.save(target)
                box = (0, 0, image.width, image.height)
            produced.append(f"assets/fig/{filename}")

            marked = image.convert("RGB")
            ImageDraw.Draw(marked).rectangle(box, outline=(220, 30, 30), width=4)
            preview_panels.append((question["item_id"], source_rel, marked))
            report_items.append({
                "item_id": question["item_id"],
                "source": source_rel,
                "source_size": [image.width, image.height],
                "crop": list(box),
                "output": f"assets/fig/{filename}",
                "kept_fraction": round(
                    (box[2] - box[0]) * (box[3] - box[1]) / (image.width * image.height), 4
                ),
            })
        figure_map[question["item_id"]] = produced

    if preview_panels:
        label_h = 34
        width = max(panel.width for _, _, panel in preview_panels)
        height = sum(panel.height + label_h + 12 for _, _, panel in preview_panels)
        sheet = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(sheet)
        y = 0
        for item_id, source, panel in preview_panels:
            draw.text((8, y + 8), f"{item_id}  {source}", fill=(30, 30, 30))
            y += label_h
            sheet.paste(panel, (0, y))
            y += panel.height + 12
        sheet.save(preview_dir / "figure-crop-preview.png")

    report = {"questions_with_figures": len(figure_map), "figure_files": len(report_items), "items": report_items}
    (preview_dir / "figure-crops.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return figure_map, report


def section_numbers(seq: str, path_depth: int) -> list[str]:
    parts = seq.split("-", 1)[0].split(".")
    prefixes = [".".join(parts[: i + 1]) for i in range(len(parts))]
    # path[0] is the chapter itself; chapter internals begin at prefix depth 2.
    return prefixes[1:1 + path_depth]


def make_chapter(question_list: list[dict], ocr_map: dict, figure_map: dict, chapter_filename: str):
    key = chapter_filename.split("-", 1)[0]
    body: list[str] = []
    warnings: list[str] = []
    current_path: list[str] = []
    pending: list[tuple[dict, str]] = []

    def one(question: dict, text: str) -> str:
        return (
            f"% ---- item_id={question['item_id']} seq={question['seq']} ----\n"
            f"\\begin{{q}}{{{question['seq']}}}{{{clean_source(question.get('source'))}}}"
            f"{{{key}:q:{question['item_id']}}}\n{text}\n\\end{{q}}"
        )

    def flush_pending():
        nonlocal pending
        while pending:
            batch, pending = pending[:2], pending[2:]
            if len(batch) == 2:
                cells = "\\hfill".join(
                    f"\\qcell{{{q['seq']}}}{{{clean_source(q.get('source'))}}}"
                    f"{{{key}:q:{q['item_id']}}}{{{text}}}"
                    for q, text in batch
                )
                body.append(f"% ---- paired compact questions ----\n\\begin{{qrow}}\n{cells}\n\\end{{qrow}}")
            else:
                body.append(one(*batch[0]))

    for question in question_list:
        inner_path = question["path"][1:]
        numbers = section_numbers(question["seq"], len(inner_path))
        if len(numbers) != len(inner_path):
            warnings.append(f"{question['item_id']}: seq/path depth mismatch")
            numbers = (numbers + numbers[-1:] * len(inner_path))[:len(inner_path)] if numbers else ["?"] * len(inner_path)
        keep = 0
        while keep < len(current_path) and keep < len(inner_path) and current_path[keep] == inner_path[keep]:
            keep += 1
        if keep < len(inner_path):
            flush_pending()
        for level in range(keep, len(inner_path)):
            body.append(
                f"\\qhead{{{level + 1}}}{{{numbers[level]}}}{{{legacy.meta(inner_path[level])}}}"
                f"{{{key}:sec:{numbers[level]}}}"
            )
        current_path = inner_path

        ocr = ocr_map[question["item_id"]]
        figs = figure_map.get(question["item_id"], [])
        text = render_question_text(question, ocr, figs, warnings)
        stem_only = legacy.clean_stem(ocr.get("latex") or "", False, ocr.get("question_type", ""))
        if legacy.is_compact(stem_only, ocr, bool(figs)):
            pending.append((question, text))
        else:
            flush_pending()
            body.append(one(question, text))
    flush_pending()

    target = OUT / "章节" / f"{chapter_filename}.tex"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n\n".join(body) + "\n", encoding="utf-8")
    return target, warnings


def prepare_preamble(template_path: Path, variant: str) -> str:
    source = template_path.read_text(encoding="utf-8")
    preamble = source[:source.index("\\begin{document}")]
    preamble = preamble.replace(
        "\\usepackage{graphicx}\n\\graphicspath{{../../_build/}}",
        "\\usepackage{graphicx}\n\\graphicspath{{../}{assets/fig/}}\n\\usepackage{pdfpages}",
        1,
    )
    preamble = re.sub(r"pdftitle=\{[^}]*\}", f"pdftitle={{{BASE_NAME}·{variant}}}", preamble, count=1)
    preamble = preamble.replace("无空做题本-留空版", f"大观严选题 · {variant}")
    preamble = preamble.replace("无空做题本", f"大观严选题 · {variant}")
    return preamble


def make_cover(variant: str) -> Path:
    text = COVER_TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("帕拉迪宇", "澄潇宇")
    subtitle = f"A4 {variant}・数学一严选题库"
    replacements = {
        r"\\newcommand\{\\BookSubtitle\}\{[^}]*\}": rf"\\newcommand{{\\BookSubtitle}}{{{subtitle}}}",
        r"\\newcommand\{\\EditionText\}\{[^}]*\}": r"\\newcommand{\\EditionText}{2027 考研数学一}",
        r"\\newcommand\{\\DocCode\}\{[^}]*\}": r"\\newcommand{\\DocCode}{PLDY-DAGUAN / SELECT-01}",
        r"\\newcommand\{\\DocVersion\}\{[^}]*\}": r"\\newcommand{\\DocVersion}{2026.09・@Kylaan整理}",
        r"\\newcommand\{\\DocScope\}\{[^}]*\}": r"\\newcommand{\\DocScope}{函数、极限与连续／一元微分／一元积分／多元微分／二重积分／微分方程／级数}",
        r"\\newcommand\{\\DocStructure\}\{.*?\}\n": (
            r"\\newcommand{\\DocStructure}{收录大观严选题数学一共 770 题；题干由 OCR-AI 结构化转写，"
            r"保留知识树、题号与题源。正文仅使用题干与选项字段，不编入答案解析图。\\ "
            r"如遇识别问题，请联系 @Kylaan（maintainer@example.invalid）。}\n"
        ),
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text, count=1, flags=re.S)
    text = text.replace(
        r"考研数学大观\\[-0.8pt]做题本",
        r"澄潇宇大观\\[-0.8pt]严选题本",
    )
    text = text.replace("$a_n\\to L$", "$t\\to\\infty$")
    target = OUT / f"{BASE_NAME}·{variant}-封皮.tex"
    target.write_text(text, encoding="utf-8")
    return target


def make_book(variant: str, template: Path, cover_tex: Path, chapter_counts: dict[str, int]) -> Path:
    preamble = prepare_preamble(template, variant)
    lines = [preamble, "\\begin{document}", "",
             f"\\includepdf[pages={{1,2}},pagecommand={{\\thispagestyle{{empty}}}}]{{{cover_tex.stem}.pdf}}", "",
             "\\pagenumbering{roman}", "\\setcounter{tocdepth}{1}", "\\tableofcontents",
             "\\clearpage", "\\pagenumbering{arabic}", ""]
    for source_title, display_title, filename in CHAPTERS:
        key = filename.split("-", 1)[0]
        lines.extend([
            f"\\bookchapter{{{display_title}}}{{{chapter_counts[source_title]}}}{{{key}:chap}}",
            f"\\input{{章节/{filename}.tex}}",
            "",
        ])
    lines.extend([
        "\\clearpage",
        f"\\includepdf[pages={{3}},pagecommand={{\\thispagestyle{{empty}}}}]{{{cover_tex.stem}.pdf}}",
        "\\end{document}",
        "",
    ])
    target = OUT / f"{BASE_NAME}·{variant}.tex"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not args.force and any(OUT.glob("*.tex")):
        raise RuntimeError(f"Generated TeX already exists in {OUT}; pass --force to rebuild")

    manifest, ocr_map = load_inputs()
    OUT.mkdir(parents=True, exist_ok=True)
    for directory in (OUT / "章节", OUT / "assets", OUT / "work"):
        if directory.exists():
            shutil.rmtree(directory)
    for base_name in (BASE_NAME, *LEGACY_BASE_NAMES):
        for path in OUT.glob(f"{base_name}*"):
            if path.is_file():
                path.unlink()

    figure_map, figure_report = make_figures(manifest, ocr_map)
    grouped = {title: [] for title, _, _ in CHAPTERS}
    for question in manifest["questions"]:
        grouped[question["path"][0]].append(question)

    chapter_counts = {title: len(items) for title, items in grouped.items()}
    all_warnings = []
    chapter_files = []
    for source_title, _, filename in CHAPTERS:
        path, warnings = make_chapter(grouped[source_title], ocr_map, figure_map, filename)
        chapter_files.append(path.name)
        all_warnings.extend(warnings)

    covers = {}
    books = {}
    for variant, template in (("无空版", SOLID_TEMPLATE), ("留空版", BLANK_TEMPLATE)):
        cover = make_cover(variant)
        book = make_book(variant, template, cover, chapter_counts)
        covers[variant] = cover.name
        books[variant] = book.name

    report = {
        "questions": len(manifest["questions"]),
        "chapter_counts": chapter_counts,
        "ocr_status": dict(Counter(ocr["status"] for ocr in ocr_map.values())),
        "possible_answer_content": sum(
            "possible_answer_content" in (ocr.get("flags") or []) for ocr in ocr_map.values()
        ),
        "body_policy": "Only OCR latex/options are typeset; image_transcriptions are excluded.",
        "chapters": chapter_files,
        "covers": covers,
        "books": books,
        "figures": figure_report,
        "warnings": all_warnings,
    }
    (OUT / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text(
        "# 大观严选题 TeX 产物\n\n"
        "- `章节/`：七章正文 TeX，供两版总册共同 `\\input`。\n"
        "- `assets/fig/`：从真正引用图形的题图中裁出的插图。\n"
        f"- `{books['无空版']}` / `{books['留空版']}`：两版总册主文件。\n"
        "- `*-封皮.tex`：封面、封二、封底；封底装饰已改为 `$t\\to\\infty$`。\n"
        "- `build-report.json`：题数、章节、插图和生成警告。\n\n"
        "正文只读取 OCR 的 `latex` 与 `options`；含答案的 `image_transcriptions` 不进入题册。\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "questions": len(manifest["questions"]),
        "chapters": chapter_counts,
        "figures": figure_report["figure_files"],
        "warnings": len(all_warnings),
        "books": books,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
