#!/usr/bin/env python3
"""把某一章的 manifest + OCR 结果组版为 LaTeX 题册。

用法:
    python tools/build_tex.py --chapter ch01-函数极限连续
输出:
    _build/<chapter>/tex/<chapter>.tex   （图片按 ../img/stem/ 相对引用）
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "_build"

# --------------------------------------------------------------------------
# 文本清理
# --------------------------------------------------------------------------

# 元数据（分类名、题源）是纯文本，必须转义；题干/选项已经是 LaTeX，不能转义。
META_ESCAPE = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}

# 数学字体里没有这些字形，且它们经常出现在 $...$ 内部，必须换成模式无关的宏。
SYMBOLS = {
    "➕": r"\ensuremath{+}", "➖": r"\ensuremath{-}",
    "✖": r"\ensuremath{\times}", "➗": r"\ensuremath{\div}",
    "Ⅰ": r"\rn{I}", "Ⅱ": r"\rn{II}", "Ⅲ": r"\rn{III}", "Ⅳ": r"\rn{IV}",
    "Ⅴ": r"\rn{V}", "Ⅵ": r"\rn{VI}",
}
for _i, _c in enumerate("①②③④⑤⑥⑦⑧⑨⑩", start=1):
    SYMBOLS[_c] = rf"\cnum{{{_i}}}"

CJK = re.compile(r"[一-鿿぀-ゟ゠-ヿ　-〿]")
CJK_RUN = re.compile(r"[^\x00-\x7F\s]+")

# 数学模式专用命令；出现在正文模式里就会编译失败
MATH_ONLY = re.compile(
    r"\\(?:d?frac|tfrac|sqrt|lim|sum|int|iint|infty|mathrm|mathbf|mathbb|mathcal|"
    r"cdot|cdots|leqslant|geqslant|neq|pm|times|div|alpha|beta|gamma|delta|theta|"
    r"varphi|lambda|xi|pi|sigma|mathring|stackrel|displaystyle|limits|left|right)\b"
    r"|[\^_]"
)
MATHSEG = re.compile(
    r"\$[^$]*\$|\\\[.*?\\\]|\\begin\{(cases|align|aligned|array|matrix|[bpv]matrix|gather)\*?\}"
    r".*?\\end\{\1\*?\}",
    re.S,
)

# OCR 还会用 TeX 原始的 $$...$$ 写行间公式（全库 496 题）。它能编译，但绕开了
# amsmath 的间距设置，也不会被 \[...\] 的规则统一处理，先换成 \[...\]。
DOLLAR_DISPLAY = re.compile(r"\$\$(.+?)\$\$", re.S)
DISPLAY_BLOCK = re.compile(r"\\\[(.*?)\\\]", re.S)
INLINE_MATH = re.compile(r"\$([^$]+)\$")
# 不能用 \b 收尾：Python 正则里 "_" 算单词字符，\lim_{x\to1} 的 \b 匹配不上，
# 结果恰恰是最需要 \displaystyle 的那些公式被跳过了。
BIG_OP = re.compile(r"\\(?:lim|sum|prod|int|iint|iiint|oint)(?![A-Za-z])")

LEAD_NUM = re.compile(r"^\s*[（(]?\d{1,3}[)）]?\s*(?:[.．、]\s*|\\quad\s+)")
OPTION_LINE = re.compile(r"^\s*[（(]?[A-D][)）.．、]\s*(?=\S)")
BLANK_RUN = re.compile(r"(?:\\_){2,}|＿{2,}|_{3,}")
# 题目是否真的需要插图，只看题干有没有引用图。
#
# 不能用 OCR 的 contains_diagram 标记：源题库把解答摘录合并进了题目卡，
# 解析里的配图会让整道题被标上 contains_diagram，于是解析的图被当成题图插进来。
# 反过来，题干只要说了「如图 / 见图 / 如右图 / 图中 / 阴影部分」，那图就是题目的一部分。
# 也不能收「图形」：「图形关于 x=0 对称」说的是函数图像，并没有配图。
FIGURE_HINT = re.compile(
    r"如图|见图|图中|图示|阴影部分"
    r"|[如见][上下左右]图|[上下左右]图|图\s*[0-9０-９]"
)


# OCR 结果里混进了字面量的反斜杠 n（不是换行符）。成因在 run_ocr_api.py 的
# 反斜杠修复：它把 \n 后面跟字母的情况当成 LaTeX 命令，而 Python 认为汉字也是字母，
# 于是 "\n证明" 里真正的换行转义被当成命令保护了下来。LaTeX 里 \n 是未定义命令。
# 只用小写字母挡：真正的 LaTeX 命令是 \neq \nabla \nu \not \newline 这些，全是小写。
# 大写不可能是命令，\nA. / \nB. 只会是“换行 + 选项标号”，必须还原成换行。
LITERAL_NL = re.compile(re.escape("\\") + r"n(?![a-z])")


def symbolize(text: str) -> str:
    """去掉 emoji / 变体选择符（CJK 字体没有字形），并替换数学模式下会缺字的符号。"""
    text = LITERAL_NL.sub("\n", text)
    out = []
    for ch in text:
        if ch in ("️", "︎", "​", "‍"):
            continue
        if ch in SYMBOLS:
            out.append(SYMBOLS[ch])
            continue
        # 🐙🖐🫚 之类。不能只看 category=="So"：🫪(U+1FAEA) 在当前 Python 的
        # Unicode 表里还是未分配（Cn），照样没有字形。星际平面里除了 CJK 扩展区
        # （U+20000 以上）都不该出现在这份题库里，一律剔除。
        if ord(ch) > 0xFFFF and not (0x20000 <= ord(ch) <= 0x3FFFF):
            continue
        out.append(ch)
    return "".join(out)


def meta(text: str) -> str:
    """元数据 -> 安全的 LaTeX 文本。先转义再替换符号宏，否则宏的反斜杠会被转义掉。"""
    escaped = "".join(META_ESCAPE.get(ch, ch) for ch in (text or ""))
    return symbolize(escaped).strip()


# 这些题型的公式压成行内 \displaystyle；解答/证明题的多步公式保持行间
INLINE_TYPES = ("fill_blank", "choice", "judgment")


def clean_stem(stem: str, has_options: bool, qtype: str = "") -> str:
    """去掉原书题号、去掉与 options 重复的内联选项行、统一填空线与公式形式。"""
    stem = normalize_dollars(symbolize(stem)).strip()
    stem = LEAD_NUM.sub("", stem, count=1)
    if has_options:
        stem = "\n".join(ln for ln in stem.split("\n") if not OPTION_LINE.match(ln)).strip()
    stem = BLANK_RUN.sub(r"\\blank{}", stem)
    stem = re.sub(r"\n{3,}", "\n\n", stem).strip()

    # 少数题干整体就是一个没有 $ 包裹的裸公式
    if stem and "$" not in stem and "\\[" not in stem \
            and not CJK.search(stem) and MATH_ONLY.search(stem):
        stem = f"\\[{stem}\\]"

    # 纯公式的解答题（没有一个汉字）也按行内处理，和填空题看齐
    formula_only = not CJK.search(outside_math(stem))
    if qtype in INLINE_TYPES or formula_only:
        stem = inline_displays(stem)
    return force_displaystyle(stem)


def normalize_dollars(text: str) -> str:
    r"""$$...$$ -> \[...\]，之后统一走 \[...\] 的那套规则。"""
    return DOLLAR_DISPLAY.sub(lambda m: "\\[" + m.group(1).strip() + "\\]", text)


def inline_displays(text: str) -> str:
    """\\[...\\] -> $\\displaystyle ...$。

    OCR 对同一类题给出的形式并不统一：有的写 \\[...\\]，有的写 $...$，有的裸公式。
    填空题和纯公式选择题一律压成行内 \\displaystyle，版式才一致，也才能两栏并排。
    多行公式（含 \\\\ 或 align/cases 环境）保持行间，不能压成行内。
    """
    def rep(m: re.Match) -> str:
        body = m.group(1).strip()
        if "\\\\" in body or "\\begin{" in body:
            return m.group(0)
        return f"$\\displaystyle {body}$"
    return DISPLAY_BLOCK.sub(rep, text)


def force_displaystyle(text: str) -> str:
    """给含大型算符（lim/sum/int/prod）的行内公式补上 \\displaystyle。

    不补的话 $\\lim_{n\\to\\infty}$ 的下标会挤到 lim 右边，和其它题不一致。
    只认大型算符：给普通分式补 \\displaystyle 会把正文行撑高。
    """
    def rep(m: re.Match) -> str:
        inner = m.group(1)
        if "\\displaystyle" in inner or not BIG_OP.search(inner):
            return m.group(0)
        return f"$\\displaystyle {inner.strip()}$"
    return INLINE_MATH.sub(rep, text)


def outside_math(latex: str) -> str:
    """抹掉所有数学片段，剩下的就是正文模式内容。"""
    return MATHSEG.sub(" ", latex).replace(r"\blank{}", " ")


def brace_balance(latex: str) -> int:
    depth = i = 0
    while i < len(latex):
        if latex[i] == "\\":
            i += 2
            continue
        if latex[i] == "{":
            depth += 1
        elif latex[i] == "}":
            depth -= 1
        i += 1
    return depth


# --------------------------------------------------------------------------
# 选项
# --------------------------------------------------------------------------

def wrap_option(latex: str) -> str:
    """OCR 有大量选项直接给裸数学（'1'、'\\dfrac{1}{2}'），正文模式下会炸。

    - 无 $ 且不含中文：整体按数学处理；
    - 无 $ 但中英数学混排（如 '0 或 \\infty'）：只把含数学命令的非中文片段包进 $；
    - 已有 $：原样保留。
    """
    s = symbolize(latex).strip()
    if not s or "$" in s or "\\[" in s:
        return s
    if not CJK.search(s):
        return f"${s}$"
    if not MATH_ONLY.search(s):
        return s
    out, last = [], 0
    for m in CJK_RUN.finditer(s):
        chunk = s[last:m.start()]
        out.append(f"${chunk.strip()}$" if MATH_ONLY.search(chunk) else chunk)
        out.append(m.group(0))
        last = m.end()
    tail = s[last:]
    out.append(f"${tail.strip()}$" if MATH_ONLY.search(tail) else tail)
    return " ".join(x for x in out if x.strip())


def render_option(latex: str) -> str:
    return force_displaystyle(inline_displays(normalize_dollars(wrap_option(latex))))


STACKED = ("lim", "sum", "prod", "int", "iint", "iiint", "oint")
ZERO_WIDTH = ("displaystyle", "textstyle", "limits", "nolimits", "left", "right",
              "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "quad", "qquad")
WORD_OPS = ("ln", "log", "exp", "sin", "cos", "tan", "cot", "sec", "csc",
            "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "max", "min",
            "mathrm", "text", "operatorname")


def _length_in_chars(dim: str) -> float:
    """把 '2cm' / '4.2em' 这类长度换算成大致的西文字符宽（10pt 下 1 字 ≈ 5pt）。"""
    m = re.match(r"\s*([0-9.]+)\s*(cm|mm|em|ex|pt|in)", dim)
    if not m:
        return 0.0
    value, unit = float(m.group(1)), m.group(2)
    pt = {"cm": 28.45, "mm": 2.845, "em": 10.0, "ex": 4.3, "pt": 1.0, "in": 72.27}[unit]
    return value * pt / 5.0


def _group(s: str, i: int) -> tuple[str, int]:
    """读取 s[i] 处的 {...}，返回 (组内内容, 组结束后的位置)。"""
    if i >= len(s) or s[i] != "{":
        return "", i
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1: j], j + 1
        j += 1
    return s[i + 1:], len(s)


def visual_width(latex: str) -> float:
    """估计排版后的横向宽度（以西文字符宽为 1）。

    不能按字符数硬数：\\frac{a}{b} 是上下叠放的，宽度是 max(a,b) 而不是 a+b；
    \\lim_{x\\to0} 的下标同样在下方；cases 是“窄而高”的。按字符数估会把窄而高的
    结构误判成超宽，选项因此被迫每个独占一行、简单填空也没法两两并排。
    """
    s = latex
    w = 0.0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "$":
            i += 1
            continue
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)", s[i:])
            if not m:                       # \\ 换行、\, 之类
                i += 2
                continue
            name = m.group(1)
            i += m.end() - 0 if False else len(m.group(0))
            if name in ZERO_WIDTH:
                continue
            if name in ("frac", "dfrac", "tfrac"):
                a, i = _group(s, i)
                b, i = _group(s, i)
                w += max(visual_width(a), visual_width(b)) + 1
                continue
            if name == "sqrt":
                a, i = _group(s, i)
                w += visual_width(a) + 1.5
                continue
            if name in STACKED:
                w += len(name)
                while i < len(s) and s[i] in "_^":
                    i += 1
                    if i < len(s) and s[i] == "{":
                        a, i = _group(s, i)
                    else:
                        a, i = s[i], i + 1
                    w = max(w, visual_width(a))   # 上下标叠在符号上下，不额外加宽
                continue
            if name in ("begin", "end"):
                a, i = _group(s, i)
                continue
            if name == "blank":            # \blank{} = 4.2em 的下划线
                w += 9
                continue
            if name in ("hspace", "hspace*"):
                a, i = _group(s, i)
                w += _length_in_chars(a)
                continue
            if name in WORD_OPS:
                w += len(name)
                continue
            w += 1.2                       # \alpha \infty \cdot ... 单个符号
            continue
        if c in "{}&":
            i += 1
            continue
        if c in "_^":                      # 普通上下标：小号字，算 0.7 宽
            i += 1
            if i < len(s) and s[i] == "{":
                a, i = _group(s, i)
            else:
                a, i = s[i] if i < len(s) else "", i + 1
            w += 0.7 * visual_width(a)
            continue
        w += 2 if ord(c) > 0x2E80 else 1
        i += 1

    # cases 是竖排的：整体宽度取最宽一行
    block = re.search(r"\\begin\{cases\}(.*?)\\end\{cases\}", latex, re.S)
    if block:
        rows = re.split(r"\\\\", block.group(1))
        inside = sum(visual_width(r) for r in rows)
        widest = max((visual_width(r) for r in rows), default=0)
        w = w - inside + widest + 1
    return w


def option_columns(options: list[dict]) -> int:
    """参考样式：短选项四栏，一般两栏，只有确实很宽时才独占一行。"""
    widest = max((visual_width(o["latex"]) for o in options), default=0)
    if widest <= 12:
        return 4
    if widest <= 46:
        return 2
    return 1


# --------------------------------------------------------------------------
# 判断一道题能不能进“两栏简单填空”
# --------------------------------------------------------------------------

# 半栏正文能放下的西文字符数。宽度模型是估算，留一点余量，
# 宁可让边缘题占整行，也不要把半栏撑出版心。
HALF_LINE = 36


def is_compact(stem: str, ocr: dict, has_figure: bool) -> bool:
    """参考样式 1：简单填空题两两并排。只有又短又规整的题才够格。"""
    if ocr.get("options") or has_figure:
        return False
    if ocr.get("question_type") not in ("fill_blank", "solution"):
        return False
    if "\\[" in stem or "cases" in stem or "\n" in stem:
        return False
    return visual_width(stem) <= HALF_LINE


def has_figure(ocr: dict) -> bool:
    """只看题干。选项里的「图形A：……」是 OCR 对选项图的文字描述，不能当作依据。"""
    return bool(FIGURE_HINT.search(ocr["latex"]))


# --------------------------------------------------------------------------
# 目录树
# --------------------------------------------------------------------------

def seq_numbers(seq: str) -> list[str]:
    """'2.2.1.8-019' -> ['2','2.2','2.2.1','2.2.1.8'] 的逐级编号前缀。"""
    parts = seq.split("-", 1)[0].split(".")
    return [".".join(parts[: i + 1]) for i in range(len(parts))]


# --------------------------------------------------------------------------
# 正文生成
# --------------------------------------------------------------------------

def render_body(q: dict, ocr: dict, warnings: list[str]) -> tuple[str, bool]:
    """返回 (题目正文, 是否含图)。正文 = 题干 + 选项 + 原图。"""
    options = ocr.get("options") or []
    stem = clean_stem(ocr["latex"], bool(options), ocr.get("question_type", ""))
    fig = has_figure(ocr)

    residue = MATH_ONLY.search(outside_math(stem))
    if residue:
        warnings.append(f"{q['qid']} 题干正文模式里仍有数学命令 {residue.group(0)!r}")
    if brace_balance(stem):
        warnings.append(f"{q['qid']} 题干花括号不配平（净 {brace_balance(stem):+d}）")
    for o in options:
        if brace_balance(o["latex"]):
            warnings.append(f"{q['qid']} 选项 {o['label']} 花括号不配平")

    parts = [stem]

    if options:
        cols = option_columns(options)
        width = {4: "0.235", 2: "0.48", 1: "0.97"}[cols]
        rows = []
        for i in range(0, len(options), cols):
            rows.append("\\hfill".join(
                f"\\opt{{{o['label']}}}{{{render_option(o['latex'])}}}"
                for o in options[i: i + cols]
            ))
        parts.append(f"\\begin{{opts}}{{{width}}}\n"
                     + "\\\\[0.3ex]\n".join(rows)
                     + "\n\\end{opts}")

    if fig:
        # 题目含图形，OCR 无法还原。附上原始截图作为兜底，人工裁剪后再替换。
        imgs = "".join(f"\\qfig{{../{p}}}" for p in q["images"]["stem"])
        parts.append(f"\\begin{{figblock}}\n{imgs}\n\\end{{figblock}}")

    return "\n".join(parts), fig


def build(chapter: str) -> Path:
    cdir = BUILD / chapter
    manifest = json.loads((cdir / "manifest.json").read_text(encoding="utf-8"))
    questions = manifest["questions"]

    ocr: dict[str, dict] = {}
    for path in (cdir / "ocr").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        ocr[data["qid"]] = data

    # 人工修正层：覆盖 OCR 结果，OCR 重跑不会丢失
    fixups = json.loads(Path(__file__).with_name("fixups.json").read_text(encoding="utf-8"))
    n_fixed = 0
    for qid, patch in fixups.items():
        if qid.startswith("_") or qid not in ocr:
            continue
        ocr[qid].update({k: v for k, v in patch.items() if not k.startswith("_")})
        n_fixed += 1

    body: list[str] = []
    current: list[str] = []
    warnings: list[str] = []
    pending: list[tuple[dict, str]] = []      # 等待配对的简单填空题
    n_fig = n_pair = 0

    def flush_pending() -> None:
        """把攒下的简单填空题两两并排输出（参考样式 1）。"""
        nonlocal n_pair
        while pending:
            batch, pending[:] = pending[:2], pending[2:]
            if len(batch) == 2:
                n_pair += 2
                cells = "\\hfill".join(
                    f"\\qcell{{{q['seq']}}}{{{meta(q.get('source') or '')}}}"
                    f"{{q:{q['qid']}}}{{{text}}}"
                    for q, text in batch
                )
                body.append(f"% ---- 两栏简单填空 ----\n\\begin{{qrow}}\n{cells}\n\\end{{qrow}}")
            else:
                q, text = batch[0]
                body.append(one_question(q, text))

    def one_question(q: dict, text: str) -> str:
        return (f"% ---- qid={q['qid']} seq={q['seq']} ----\n"
                f"\\begin{{q}}{{{q['seq']}}}{{{meta(q.get('source') or '')}}}{{q:{q['qid']}}}\n"
                f"{text}\n\\end{{q}}")

    for q in questions:
        # 保持原始文本；转义与符号替换都交给 meta()。
        # 先 symbolize 再 meta 会把宏里的反斜杠再转义一次，标题会印出 \ensuremath{-} 字样。
        path = list(q["path"])
        nums = seq_numbers(q["seq"])
        if len(nums) != len(path):
            warnings.append(f"{q['qid']} seq={q['seq']} 与 path 深度不一致")
            nums = (nums + nums[-1:] * len(path))[: len(path)]

        keep = 0
        while keep < len(current) and keep < len(path) and current[keep] == path[keep]:
            keep += 1
        if keep < len(path):
            flush_pending()          # 换分类前先把待配对的填空题冲掉
        for level in range(keep, len(path)):
            body.append(
                f"\\qhead{{{level + 1}}}{{{nums[level]}}}{{{meta(path[level])}}}"
                f"{{sec:{nums[level]}}}"
            )
        current = path

        item = ocr.get(q["qid"])
        if not item:
            warnings.append(f"{q['qid']} 缺少 OCR 结果，已跳过")
            continue

        text, fig = render_body(q, item, warnings)
        n_fig += fig
        stem_only = clean_stem(item["latex"], False, item.get("question_type", ""))
        if is_compact(stem_only, item, fig):
            pending.append((q, text))
        else:
            flush_pending()
            body.append(one_question(q, text))

    flush_pending()

    n_done = sum(1 for q in questions if q["qid"] in ocr)
    tex = PREAMBLE.format(
        title=meta(manifest["chapter"]),
        subtitle=f"共 {n_done} 题",
    ) + "\n\n" + "\n\n".join(body) + "\n\n\\end{document}\n"

    outdir = cdir / "tex"
    outdir.mkdir(exist_ok=True)
    out = outdir / f"{chapter}.tex"
    out.write_text(tex, encoding="utf-8")

    print(f"写入 {out}")
    print(f"  题目 {n_done}/{len(questions)}   人工修正 {n_fixed}")
    print(f"  两栏简单填空 {n_pair} 题   含图附原图 {n_fig} 题")
    for w in warnings:
        print("  警告:", w)
    return out


# --------------------------------------------------------------------------
# 导言区：所有版式都在这里
# --------------------------------------------------------------------------

PREAMBLE = r"""% !TEX program = xelatex
% 由 tools/build_tex.py 自动生成，请勿直接手改；改样式改脚本里的 PREAMBLE。
\documentclass[UTF8,10pt,a4paper]{{ctexart}}

\usepackage{{amsmath, amssymb}}
\usepackage{{graphicx}}
\usepackage[table]{{xcolor}}
\usepackage{{geometry}}
\usepackage{{lastpage}}
\usepackage{{fancyhdr}}
\usepackage{{hyperref}}

\geometry{{top=2.0cm, bottom=2.0cm, left=1.9cm, right=1.9cm,
          headsep=4mm, footskip=9mm}}

% OCR 结果里中文标点会出现在 $...$ 内部（如 $x\to0。$），
% 不开这个开关的话数学字体没有该字形，xelatex 会静默丢字。
\xeCJKsetup{{CJKmath=true}}

% ①②③ 与 Ⅰ Ⅱ 同样会出现在数学模式里，用与模式无关的宏顶替。
\newcommand{{\cnum}}[1]{{\ensuremath{{\text{{\textcircled{{\scriptsize #1}}}}}}}}
\newcommand{{\rn}}[1]{{\ensuremath{{\mathrm{{#1}}}}}}

\definecolor{{ink}}{{HTML}}{{1A1A1A}}
\definecolor{{accent}}{{HTML}}{{16506B}}
\definecolor{{soft}}{{HTML}}{{8A8A8A}}
\definecolor{{rule}}{{HTML}}{{D6DEE3}}

\hypersetup{{
  colorlinks=true, linkcolor=accent, urlcolor=accent,
  bookmarksnumbered=true, bookmarksopen=true, bookmarksopenlevel=2,
  pdftitle={{{title}}},
}}

\color{{ink}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0pt}}
\linespread{{1.15}}
\allowdisplaybreaks[4]
\setlength{{\emergencystretch}}{{1.5em}}

\setlength{{\abovedisplayskip}}{{4pt plus 2pt minus 1pt}}
\setlength{{\belowdisplayskip}}{{4pt plus 2pt minus 1pt}}
\setlength{{\abovedisplayshortskip}}{{2pt plus 1pt}}
\setlength{{\belowdisplayshortskip}}{{2pt plus 1pt}}

% ======== 可调版式参数 ========
\newlength{{\qsep}}     \setlength{{\qsep}}{{8ex}}      % 题与题之间的间距（留空版就是加大它）
\newlength{{\qheadgap}} \setlength{{\qheadgap}}{{1.2ex}} % 小标题与它下面第一道题的间距
\newlength{{\qhdrsep}}  \setlength{{\qhdrsep}}{{1.1ex}}  % 题号行与题干之间的间距
\newlength{{\qindent}}  \setlength{{\qindent}}{{1.7em}}  % 题干相对题号的缩进

% 「刚打完一个小标题」的标志。
% 每道题开头都要空出 \qsep，但紧跟在标题后面的第一道题不能空——否则标题和它的
% 第一道题之间被撑开一个 \qsep 的大洞，标题看起来就孤零零地悬着。间距越大越明显。
% 所以标题结束时立旗，题目开头看到旗就改用 \qheadgap，并把旗放倒。
\newif\ifqafterhead \qafterheadfalse

% ---------------- 页眉页脚 ----------------
\pagestyle{{fancy}}
\fancyhf{{}}
\renewcommand{{\headrulewidth}}{{0.4pt}}
\fancyhead[L]{{\small\color{{soft}}{title}}}
\fancyhead[R]{{\small\color{{soft}}\leftmark}}
\fancyfoot[C]{{\small\color{{soft}}· 第 \thepage{{}} 页，共 \pageref{{LastPage}} 页 ·}}

% ---------------- 分类标题 ----------------
% \qhead{{层级}}{{编号}}{{标题}}{{锚点}}
\newcommand{{\qhead}}[4]{{%
  \par\phantomsection\label{{#4}}%
  \ifnum#1=1
    \addvspace{{2.4ex}}\pdfbookmark[1]{{#2 #3}}{{#4}}%
    \markboth{{#2\quad #3}}{{#2\quad #3}}%
    \addcontentsline{{toc}}{{section}}{{\protect\numberline{{#2}}#3}}%
    {{\color{{accent}}\hrule height 1.2pt}}\vspace{{0.7ex}}%
    {{\LARGE\bfseries\color{{accent}} #2\hspace{{0.6em}}#3}}%
    \par\vspace{{0.3ex}}\addvspace{{1.6ex}}%
  \else\ifnum#1=2
    \addvspace{{2.0ex}}\pdfbookmark[2]{{#2 #3}}{{#4}}%
    \addcontentsline{{toc}}{{subsection}}{{\protect\numberline{{#2}}#3}}%
    {{\large\bfseries\color{{accent}} #2\hspace{{0.5em}}#3}}%
    \par\vspace{{0.4ex}}{{\color{{rule}}\hrule height 0.5pt}}\addvspace{{1.2ex}}%
  \else\ifnum#1=3
    \addvspace{{1.7ex}}\pdfbookmark[3]{{#2 #3}}{{#4}}%
    {{\normalsize\bfseries\color{{accent}} #2\hspace{{0.5em}}#3}}\par\addvspace{{0.8ex}}%
  \else
    \addvspace{{1.4ex}}\pdfbookmark[#1]{{#2 #3}}{{#4}}%
    \hspace*{{\dimexpr 0.9em*(#1-4)\relax}}%
    {{\normalsize\bfseries\color{{soft}}$\blacktriangleright$\,}}%
    {{\normalsize\bfseries #2\hspace{{0.45em}}#3}}\par\addvspace{{0.6ex}}%
  \fi\fi\fi
  \global\qafterheadtrue
  \nopagebreak                 % 标题不要单独留在页底
}}

% ---------------- 题目 ----------------
% 题头：题号 + 唯一出处（数据库 ZNOTETITLE）
\newcommand{{\qhdr}}[2]{{%
  {{\bfseries\color{{accent}} #1}}%
  \ifx\relax#2\relax\else\hspace{{0.55em}}{{\small\color{{soft}} #2}}\fi
}}

% \begin{{q}}{{题号}}{{出处}}{{锚点}}
\newenvironment{{q}}[3]{{%
  \par
  \ifqafterhead
    \nobreak\vspace{{\qheadgap}}\global\qafterheadfalse
  \else
    \addvspace{{\qsep}}\penalty-200%
  \fi
  \phantomsection\label{{#3}}%
  \noindent\qhdr{{#1}}{{#2}}%
  \par\nobreak\vspace{{\qhdrsep}}%
  \begingroup\leftskip=\qindent\nobreak
}}{{%
  \par\endgroup%
}}

% 两栏简单填空：\begin{{qrow}} \qcell{{号}}{{出处}}{{锚点}}{{正文}} \hfill \qcell{{...}} \end{{qrow}}
\newenvironment{{qrow}}{{%
  \par
  \ifqafterhead
    \nobreak\vspace{{\qheadgap}}\global\qafterheadfalse
  \else
    \addvspace{{\qsep}}%
  \fi
  \noindent
}}{{%
  \par
}}
\newcommand{{\qcell}}[4]{{%
  \parbox[t]{{0.48\linewidth}}{{%
    \phantomsection\label{{#3}}\sloppy
    \qhdr{{#1}}{{#2}}\par\vspace{{\qhdrsep}}%
    \leftskip=0.9em\relax #4\strut}}%
}}

% 填空线
\newcommand{{\blank}}{{\underline{{\hspace{{4.2em}}}}}}

% 选项：参考样式用 “A.”，短选项四栏 / 一般两栏 / 超宽独占一行
\newlength{{\optwd}}
\newenvironment{{opts}}[1]{{%
  \par\addvspace{{0.5ex}}%
  \setlength{{\optwd}}{{#1\dimexpr\linewidth\relax}}%
  \setlength{{\topsep}}{{0pt}}\setlength{{\partopsep}}{{0pt}}%
  \setlength{{\parsep}}{{0pt}}\setlength{{\itemsep}}{{0pt}}%
  \begin{{trivlist}}\item[]\relax
}}{{%
  \end{{trivlist}}%
}}
\newcommand{{\opt}}[2]{{%
  \parbox[t]{{\optwd}}{{\raggedright\sloppy\hangindent=1.5em\hangafter=1
    {{\bfseries #1.}}\hspace{{0.4em}}#2\strut}}%
}}

% 含图题：build_tex 先贴整张原始截图（图文都在里面），人工确认哪些题真的需要图之后，
% 用 tools/crop_figs.py 把图形裁出来放进 img/fig/，并把下面的引用改指过去。
% 截图是 165 DPI，按 72/165≈0.44 缩放即原始物理尺寸；过宽的（如整排选项图）压到版心内。
\newenvironment{{figblock}}{{%
  \par\addvspace{{0.8ex}}\begingroup\centering
}}{{%
  \par\endgroup\addvspace{{0.6ex}}%
}}
% 验收对照用：tools/figs_both.py 会往正文插入原图，验收完 --clean 移除
\newcommand{{\figlabel}}[1]{{\par\vspace{{0.3ex}}{{\scriptsize\color{{soft}} #1}}\par}}
\newcommand{{\figraw}}[2]{{%
  \par\vspace{{0.5ex}}%
  {{\scriptsize\color{{soft}} #2}}\par\vspace{{0.2ex}}%
  \fbox{{\includegraphics[width=0.92\linewidth]{{#1}}}}\par
}}

\newlength{{\figw}}
\newcommand{{\qfig}}[1]{{%
  \settowidth{{\figw}}{{\includegraphics[scale=0.44]{{#1}}}}%
  \ifdim\figw>0.62\linewidth
    \includegraphics[width=0.62\linewidth]{{#1}}%
  \else
    \includegraphics[scale=0.44]{{#1}}%
  \fi
  \hspace{{1.5em}}%
}}

\begin{{document}}

\begin{{titlepage}}
\centering
\vspace*{{6cm}}
{{\color{{accent}}\hrule height 2pt}}
\vspace{{1.2em}}
{{\Huge\bfseries {title}}}\par
\vspace{{1.0em}}
{{\large\color{{soft}} {subtitle}|重构自：大观MarginNote源文件\vspace{{0.7em}}\\ 勘误请参考：https://kylaan.github.io/pldy-daguan-export/}}\par
\vspace{{1.2em}}
{{\color{{accent}}\hrule height 2pt}}
\vfill
{{\small\color{{soft}} 由 MarginNote 题库中间层重排；题干经 OCR 重新识别，不含答案。\\}}{{\small\color{{red}}纠错请联系@Kylaan}}\par
\vspace{{2cm}}
\end{{titlepage}}

\pagenumbering{{roman}}
\setcounter{{tocdepth}}{{2}}
\tableofcontents
\clearpage
\pagenumbering{{arabic}}
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="ch01-函数极限连续")
    args = ap.parse_args()
    build(args.chapter)
