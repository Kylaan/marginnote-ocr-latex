"""Typeset the 391-question bank, preserving OCR and applying manual overlays."""
import json
import re
import os
from collections import Counter
from pathlib import Path
from PIL import Image
import typeset_base as base

BANK = Path(__file__).resolve().parents[2]
OUT = BANK / 'tex'
TEMPLATES = Path(__file__).parent / 'templates'
NAME = '澄潇宇大观题库-多元积分'
CHAPTERS = [
    ('空间解析几何', '第一章 空间解析几何', 'ch01-空间解析几何'),
    ('三重积分', '第二章 三重积分', 'ch02-三重积分'),
    ('线面积分', '第三章 线面积分', 'ch03-线面积分'),
]
FIGURES = {
    'c340b16c6ba4': (410, 125, 675, 380),
    'c45d9b70090b': (470, 120, 695, 307),
    '7b170a949815': (800, 175, 1105, 446),
}
LAYOUT = {
    '1e6ce5613949': r'''下列结论
\[
\begin{aligned}
\text{\cnum{1} }&\oint_{x^2+y^2=a^2}(x^2+y^2)\,ds
 =a^2\oint_{x^2+y^2=a^2}ds=2\pi a^3;\\
\text{\cnum{2} }&\iint_{x^2+y^2\le a^2}(x^2+y^2)\,d\sigma
 =a^2\iint_{x^2+y^2\le a^2}d\sigma=\pi a^4;\\
\text{\cnum{3} }&\oiint_{x^2+y^2+z^2=a^2}(x^2+y^2+z^2)\,dS
 =a^2\oiint_{x^2+y^2+z^2=a^2}dS=4\pi a^4;\\
\text{\cnum{4} }&\iiint_{x^2+y^2+z^2\le a^2}(x^2+y^2+z^2)\,dv
 =a^2\iiint_{x^2+y^2+z^2\le a^2}dv=\frac{4}{3}\pi a^5.
\end{aligned}
\]
中正确的个数为''',
    '0ee0a6ac61d9': r'''设 $\Sigma$ 为曲面 $z=\sqrt{1-x^2-y^2}$，$\alpha$，$\beta$ 分别为曲面 $\Sigma$ 的外法线向量与 $x$ 轴，$z$ 轴的夹角，则
\[
\begin{aligned}
\iint_{\Sigma}\left(|xy|\cos\alpha+z^2\cos\beta\right)dS=\underline{\hspace{4em}}.
\end{aligned}
\]''',
}


def replace_macro(text, name, value):
    pattern = r'\\newcommand\{\\' + re.escape(name) + r'\}\{.*?\}\n'
    return re.sub(pattern, lambda _: '\\newcommand{\\' + name + '}{' + value + '}\n', text, count=1, flags=re.S)


def cover(variant):
    text = (TEMPLATES / '无空版-封皮.tex').read_text(encoding='utf-8')
    values = {
        'BookSubtitle': f'A4 {variant}・多元积分完整题库',
        'OwnerName': r'bilibili@澄潇宇 \hspace{3.8cm}',
        'EditionText': '2027 考研数学一',
        'DocCode': 'DAGUAN / MULTIVARIATE-01',
        'DocVersion': '2026.09・@Kylaan整理',
        'DocScope': '空间解析几何（113题）／三重积分（44题）／线面积分（234题）',
        'DocStructure': r'收录完整题库共391题，保留知识树顺序、题号与题源。题干和公式由OCR转写；仅编入题目和选项，不编入答案解析。\\ 留空版增加演算空间，无空版紧凑排列。缺失的第二问已对照原书题图补齐。',
        'DocNote': '低头看路，抬头看天',
    }
    for name, value in values.items():
        text = replace_macro(text, name, value)
    text = text.replace(r'考研数学大观\\[-0.8pt]做题本', r'澄潇宇大观\\[-0.8pt]做题本')
    text = text.replace('高等数学篇', '空间解析几何・三重积分・线面积分')
    text = text.replace('INDEX / 01--07', 'INDEX / 01--03')
    text = text.replace(r'$a_n\to L$', r'$t\to\infty$')
    text = text.replace('lualatex', 'xelatex')
    # Installed Noto SC variable fonts are rejected by this XeTeX PDF driver.
    font_config = BANK / 'config/fonts.json'
    fonts = json.loads(font_config.read_text(encoding='utf-8')) if font_config.exists() else {}
    sans = fonts.get('cover_sans', 'Microsoft YaHei' if os.name == 'nt' else 'FandolHei-Regular')
    serif = fonts.get('cover_serif', 'SimSun' if os.name == 'nt' else 'FandolSong-Regular')
    for value in (sans, serif):
        if any(c in value for c in '{}\\\n\r'):
            raise ValueError('Invalid font name')
    text = text.replace('Noto Sans SC', sans).replace('Noto Serif SC', serif)
    text = text.replace('・', '·')
    path = OUT / f'{NAME}·{variant}-封皮.tex'
    path.write_text(text, encoding='utf-8')
    return path


def main():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    ocr = {q['item_id']: json.loads((BANK / 'json/ocr/question' / (q['item_id'] + '.json')).read_text(encoding='utf-8')) for q in manifest['questions']}
    fixups = json.loads((BANK / 'json/manual/fixups.json').read_text(encoding='utf-8'))
    for item_id, patch in fixups.items():
        ocr[item_id].update({key: value for key, value in patch.items() if not key.startswith('_')})
    base.BANK = BANK
    base.OUT = OUT
    base.BASE_NAME = NAME
    base.CHAPTERS = CHAPTERS
    base.STEM_LAYOUT_OVERRIDES = LAYOUT
    OUT.mkdir(exist_ok=True)
    figures = {}
    figdir = OUT / 'assets/fig'
    figdir.mkdir(parents=True, exist_ok=True)
    for item_id, box in FIGURES.items():
        path = figdir / f'{item_id}-01.png'
        with Image.open(BANK / 'img/question' / f'{item_id}-01.png') as image:
            image.crop(box).save(path)
        figures[item_id] = [f'assets/fig/{path.name}']
    expected_figures = {qid for qid, data in ocr.items() if base.legacy.has_figure(data)}
    assert expected_figures == set(FIGURES), f'Unhandled figures: {expected_figures.symmetric_difference(FIGURES)}'
    grouped = {name: [q for q in manifest['questions'] if q['path'][0] == name] for name, _, _ in CHAPTERS}
    warnings = []
    for name, _, filename in CHAPTERS:
        chapter, found = base.make_chapter(grouped[name], ocr, figures, filename)
        text = chapter.read_text(encoding='utf-8')
        # Keep the three diagrams with their question text and options.
        for item_id in figures:
            pattern = r'(% ---- item_id=' + item_id + r' seq=[^\n]* ----\n)(\\begin\{q\}.*?\\end\{q\})'
            text = re.sub(pattern, lambda m: m.group(1) + '\\par\\addvspace{\\qsep}\\noindent\n\\begin{minipage}{\\linewidth}\n' + m.group(2) + '\n\\end{minipage}\n', text, flags=re.S)
        # A stack of subsection headings belongs with its first question.
        # Keep its marks outside the box so running headers still update.
        head_pattern = r'((?:\\qhead[^\n]*\n\s*)+)(%[^\n]*\n)(\\begin\{(q|qrow)\}.*?\\end\{\4\})'
        def keep_heading(match):
            heads = match.group(1)
            metadata = re.findall(r'\\qhead\{\d+\}\{([^}]*)\}\{(.*?)\}\{[^}]*\}', heads)
            number, title = metadata[-1]
            return '\\par\\addvspace{2.4ex}\\noindent\n\\begin{minipage}{\\linewidth}\n' + heads + match.group(2) + match.group(3) + '\n\\end{minipage}\n\\markboth{' + number + '\\quad ' + title + '}{' + number + '\\quad ' + title + '}\n'
        text = re.sub(head_pattern, keep_heading, text, flags=re.S)
        chapter.write_text(text, encoding='utf-8')
        warnings.extend(found)
    counts = {name: len(items) for name, items in grouped.items()}
    books = {}
    for variant in ('无空版', '留空版'):
        cover_path = cover(variant)
        book = base.make_book(variant, TEMPLATES / f'{variant}.tex', cover_path, counts)
        text = book.read_text(encoding='utf-8')
        font_config = BANK / 'config/fonts.json'
        fonts = json.loads(font_config.read_text(encoding='utf-8')) if font_config.exists() else {}
        fontset = fonts.get('body_fontset', 'auto')
        if fontset not in ('auto', 'windows', 'fandol', 'mac'):
            raise ValueError('Unsupported ctex fontset')
        if fontset != 'auto':
            text = text.replace('\\documentclass[UTF8,10pt,a4paper]', '\\documentclass[UTF8,10pt,a4paper,fontset=' + fontset + ']')
        text = text.replace('大观严选题', '多元积分题库')
        text = text.replace(r'\usepackage{amsmath, amssymb}', r'\usepackage{amsmath, amssymb}' + '\n' + r'\usepackage{esint}')
        text = text.replace('bookmarksnumbered=true,', 'bookmarksnumbered=true, bookmarksdepth=7,')
        # Explicit bookmarks preserve every source level; write visible TOC
        # entries without creating a second bookmark for the same heading.
        text = text.replace(r'\addcontentsline{toc}{section}{\protect\numberline{#2}#3}', r'\addtocontents{toc}{\protect\contentsline{section}{\protect\numberline{#2}#3}{\thepage}{#4.1}}')
        text = text.replace(r'\addcontentsline{toc}{subsection}{\protect\numberline{#2}#3}', r'\addtocontents{toc}{\protect\contentsline{subsection}{\protect\numberline{#2}#3}{\thepage}{#4.2}}')
        text = text.replace(r'\addcontentsline{toc}{part}{#1}', r'\addtocontents{toc}{\protect\contentsline{part}{#1}{\thepage}{#3.0}}')
        # Covers are outside the body's page total.
        text = text.replace('\\clearpage\n\\includepdf[pages={3}', '\\label{BodyLastPage}\n\\clearpage\n\\includepdf[pages={3}')
        text = text.replace(r'\pageref{LastPage}', r'\pageref{BodyLastPage}')
        text = text.replace(r'\fancyhead[R]{\small\color{soft}\leftmark}', r'\fancyhead[R]{\scriptsize\color{soft}\leftmark}')
        book.write_text(text, encoding='utf-8')
        books[variant] = book.name
    report = {'questions': len(manifest['questions']), 'chapter_counts': counts, 'ocr_status_after_review': dict(Counter(data['status'] for data in ocr.values())), 'manual_review_items': list(fixups), 'figures': figures, 'books': books, 'warnings': warnings, 'body_policy': 'Only latex/options; no answer or image_transcriptions content.'}
    (OUT / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
