#!/usr/bin/env python3
"""把含图题的“整张题目截图”裁成“只剩图形”。

题图截图里图文混排，直接贴上去等于把题干印两遍。这里自动定位图形区域：
坐标轴是长直线，一列上连续墨迹的长度远超正文字符高度；文字则是一行行的矮墨迹。
因此“存在超长竖直墨迹”的列就是图形所在，再把与之连通的墨迹一起框进来。

产物：
    img/fig/<qid>.png        裁好的图形
    _crop_preview.png        原图 + 红框的对照长图，人工复核用（复核完可删）
并把 tex 里的 \\qfig{../img/stem/...} 改指到 ../img/fig/...

用法:
    python tools/crop_figs.py --chapter ch02-一元微分 --preview   # 只出对照图，不改 tex
    python tools/crop_figs.py --chapter ch02-一元微分             # 裁图并改 tex
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]

INK = 200          # 灰度低于此值算墨迹
PAD = 10           # 裁剪边距

# 截图都是 1120px 宽、约 165 DPI，正文一行高约 40px，所以下面用绝对像素是稳的。
DILATE_X = 12      # 横向膨胀：把一行里的字连成一条，图形的线条不受影响
DILATE_Y = 2
MIN_AREA = 120     # 噪点
TEXT_H = 62        # 高度小于它 -> 一行文字
WIDE_TEXT_H = 105  # 高度小于它且又长又扁 -> 带分式的文字行
WIDE_RATIO = 5.0
NEAR = 30          # 图形附近这个距离内的小块（坐标轴标注、(A)(B) 编号）一并框进来

# 自动判定不准的在这里手写。值可以是一个 (left, top, right, bottom)，
# 也可以是多个框——题图和选项图被题干夹在中间时，一个矩形框不出来，只能切两张。
OVERRIDES: dict[str, list[tuple[int, int, int, int]]] = {
    # 题图在右上、题干在中间、四个选项图在下方：切成“题图”和“选项图”两张
    "dea537304fb4-1": [(826, 0, 1120, 213), (0, 210, 1120, 460)],
}


def components(im: Image.Image) -> list[tuple[int, int, int, int, int]]:
    """连通块分析，返回 [(x0, y0, x1, y1, 面积)]。

    先做横向为主的膨胀：一行文字里的字被连成一条长条，而图形的线条形状不变。
    这样“又长又扁”就成了文字的特征，“又高又方”就成了图形的特征。
    """
    g = im.convert("L")
    w, h = g.size
    px = g.load()

    ink = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            if px[x, y] < INK:
                ink[row + x] = 1

    # 膨胀（横 DILATE_X、纵 DILATE_Y）
    dil = bytearray(w * h)
    for y in range(h):
        row = y * w
        runs = []
        x = 0
        while x < w:
            if ink[row + x]:
                s = x
                while x < w and ink[row + x]:
                    x += 1
                runs.append((s, x - 1))
            else:
                x += 1
        for s, e in runs:
            a, b = max(0, s - DILATE_X), min(w - 1, e + DILATE_X)
            for yy in range(max(0, y - DILATE_Y), min(h - 1, y + DILATE_Y) + 1):
                r2 = yy * w
                for xx in range(a, b + 1):
                    dil[r2 + xx] = 1

    # 连通块（并查集，4 邻域足够，因为已经膨胀过）
    parent = list(range(w * h))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if not dil[i]:
                continue
            if x and dil[i - 1]:
                union(i, i - 1)
            if y and dil[i - w]:
                union(i, i - w)

    boxes: dict[int, list[int]] = {}
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if not dil[i]:
                continue
            r = find(i)
            b = boxes.get(r)
            if b is None:
                boxes[r] = [x, y, x, y, 1]
            else:
                if x < b[0]:
                    b[0] = x
                if x > b[2]:
                    b[2] = x
                if y < b[1]:
                    b[1] = y
                if y > b[3]:
                    b[3] = y
                b[4] += 1
    return [tuple(b) for b in boxes.values() if b[4] >= MIN_AREA]


def is_text(b: tuple[int, int, int, int, int]) -> bool:
    h = b[3] - b[1] + 1
    w = b[2] - b[0] + 1
    if h < TEXT_H:                                   # 普通文字行
        return True
    if h < WIDE_TEXT_H and w / h > WIDE_RATIO:       # 含分式、又长又扁的文字行
        return True
    return False


def detect(im: Image.Image) -> tuple[int, int, int, int] | None:
    comps = components(im)
    figs = [b for b in comps if not is_text(b)]
    if not figs:
        return None

    x0 = min(b[0] for b in figs)
    y0 = min(b[1] for b in figs)
    x1 = max(b[2] for b in figs)
    y1 = max(b[3] for b in figs)

    # 把紧挨着图形的小块（坐标轴标注 x/y/O、选项编号 (A)(B)）也框进来
    for _ in range(3):
        for b in comps:
            if b in figs:
                continue
            if (b[0] >= x0 - NEAR and b[2] <= x1 + NEAR
                    and b[1] >= y0 - NEAR and b[3] <= y1 + NEAR):
                figs.append(b)
                x0, y0 = min(x0, b[0]), min(y0, b[1])
                x1, y1 = max(x1, b[2]), max(y1, b[3])

    w, h = im.size
    return (max(0, x0 - PAD), max(0, y0 - PAD),
            min(w, x1 + 1 + PAD), min(h, y1 + 1 + PAD))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="ch02-一元微分")
    ap.add_argument("--preview", action="store_true", help="只生成对照图，不裁剪、不改 tex")
    args = ap.parse_args()

    cdir = ROOT / "_build" / args.chapter
    tex = cdir / "tex" / f"{args.chapter}.tex"
    text = tex.read_text(encoding="utf-8")

    refs = re.findall(r"\\qfig\{\.\./(img/stem/([^}/]+)\.png)\}", text)
    if not refs:
        print("tex 里没有 \\qfig，无需处理")
        return 0

    figdir = cdir / "img" / "fig"
    figdir.mkdir(parents=True, exist_ok=True)

    panels, report = [], []
    produced: dict[str, list[str]] = {}
    for rel, name in refs:
        src = cdir / rel
        im = Image.open(src)
        boxes = OVERRIDES.get(name)
        if boxes is None:
            one = detect(im)
            boxes = [one] if one else []
        if not boxes:
            # 检不出图形 = 这张根本不是图，而是题干续页或整页解析截图。
            # 它的文字 OCR 已经转写过了，贴上去只会重复，直接丢掉。
            report.append((name, im.size, None))
            produced[name] = []
            panels.append(im.convert("RGB"))
            continue

        marked = im.convert("RGB")
        draw = ImageDraw.Draw(marked)
        names = []
        for i, box in enumerate(boxes):
            report.append((name, im.size, box))
            draw.rectangle(box, outline=(220, 30, 30), width=4)
            stem = name if len(boxes) == 1 else f"{name}{chr(97 + i)}"
            names.append(stem)
            if not args.preview:
                im.crop(box).save(figdir / f"{stem}.png")
        produced[name] = names
        panels.append(marked)

    # 对照长图
    width = max(p.width for p in panels)
    total = sum(p.height + 12 for p in panels)
    sheet = Image.new("RGB", (width, total), (255, 255, 255))
    y = 0
    for p in panels:
        sheet.paste(p, (0, y))
        y += p.height + 12
    sheet.save(cdir / "tex" / "_crop_preview.png")

    for name, size, box in report:
        if box is None:
            print(f"  {name}  {size[0]}x{size[1]}  未检出图形 -> 保持原图")
        else:
            w, h = box[2] - box[0], box[3] - box[1]
            keep = 100 * w * h / (size[0] * size[1])
            print(f"  {name}  {size[0]}x{size[1]} -> {w}x{h}  (保留 {keep:.0f}%)")

    if args.preview:
        print(f"\n对照图: {cdir / 'tex' / '_crop_preview.png'}（未改 tex）")
        return 0

    def relink(m: re.Match) -> str:
        name = m.group(1)
        if name not in produced:
            return m.group(0)                      # 没处理过的，原样保留
        return "".join(f"\\qfig{{../img/fig/{n}.png}}" for n in produced[name])

    new = re.sub(r"\\qfig\{\.\./img/stem/([^}/]+)\.png\}", relink, text)
    # 图全被丢掉的题，figblock 就空了，整块删掉
    new, empty = re.subn(r"\n?\\begin\{figblock\}\s*\n?\s*\\end\{figblock\}\n?", "\n", new)
    tex.write_text(new, encoding="utf-8")

    dropped = sum(1 for v in produced.values() if not v)
    print(f"\n裁出图形 {sum(len(v) for v in produced.values())} 张，tex 已改指 ../img/fig/")
    print(f"丢弃非图截图 {dropped} 张（题干续页/整页解析），清掉空 figblock {empty} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
