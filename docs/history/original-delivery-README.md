# 多元积分完整题库（含答案）· 拆包工作目录

从同级原始 `.marginpkg` 拆出完整 SQLite 数据库，恢复 MarginNote 目录树并导出原始 PNG。交付日期：2026-09-30。

数据库主目录名为「三重线面积分」，共 391 道题：空间解析几何 113 题、三重积分 44 题、线面积分 234 题。保留脑图顺序、题源、来源书名、页码、文字层与合并摘录关系。

| 内容 | 数量 |
|---|---:|
| 题目 | 391 |
| 主卡题图 | 401 |
| 合并摘录图 | 514 |
| 缺少题图的题目 | 0 |
| 有合并摘录图的题目 | 368 |
| 重复 qid | 0 |
| 未导出的数据库 PNG 媒体 | 0 |

## 工作文件

- `source/`：完整解包数据库，可继续查询全部节点、坐标 JSON 和其他媒体。
- `img/question/`：主卡聚合 PNG 减去合并摘录 PNG 后得到的题图，保持数据库原始字节。
- `img/related/`：关联摘录，通常是答案/解析，也可能是题干续页；按来源页码和位置排序。
- `img/answer/`：预留给复核确认的答案图，目前为空。
- `manifest.json`：后续处理的事实源，含每题稳定 qid、item_id、目录路径、图片路径、来源信息及关联摘录。
- `tree.json` / `outline.md`：机器可读目录树 / 人读目录。
- `review.html`：离线图片校对页，可直接在浏览器打开；合并摘录默认折叠。
- `extraction-report.json`：包和数据库 SHA-256、源表计数、媒体类型和导出统计。本库只有一个有效根，没有排除其他根。
- `workflow.json`：拆包、题干 OCR、重点复核和双版本排版已完成；答案摘录分类与答案 OCR 尚未开始。
- `json/ocr/question/`、`json/ocr/answer/`、`json/manual/`、`tex/`：后续工作目录。
- `work/ocr-ai/`：沿用前一个题库的忠实转写提示词、输出 Schema 和调用约定。
- `work/logs/validation.json`：全量图片 SHA-256、尺寸、字节数及验证结果。
- `work/review/extraction-samples.jpg`：三部分各取一题的题图/关联摘录抽样对照。
- `tools/`：自包含拆包与校验脚本。

## 校验结果与处理边界

原包 ZIP CRC、SQLite integrity_check、数据库 SHA-256、题目 ID 唯一性、目录树与 manifest 顺序均通过检查。全部 915 张 PNG 可解码，导出字节与数据库载荷逐张一致，数据库 PNG 媒体全部覆盖。

抽样检查了三个部分的题图和关联摘录，拆分正常。尚未逐题判定每张关联摘录的语义。题干 OCR 和题册排版已完成，见下方交付记录。合并摘录不能仅凭“含答案”的包名直接分类为答案；转写题干时先使用 images.question，避免混入解析。数据库文字层仅供参考，数学公式以图片为准。

## 复核与重跑

脚本使用 Python 3；校验图片需要 Pillow。已使用 Python 3.13.6、Pillow 12.0.0 验证本交付。

在本目录执行校验：

```powershell
python .\tools\verify.py
```

从原包重新生成一个新目录：

```powershell
python .\tools\export_package.py '..\多元积分完整题库（含答案）(2026-09-30-12-28-06).marginpkg' '..\多元积分完整题库（含答案）-重新拆包'
```

重跑脚本拒绝覆盖已有目录，复制完整数据库和工具并执行全量校验。新目录的 README.md 为自动生成版本。原始 marginpkg 保留在同级目录，未修改。


## OCR 与 PDF 交付（2026-09-30）

`交付成果.zip` 已完整解包归档到 `产物/`；391 个 OCR JSON 同时归入标准目录 `json/ocr/question/`，逐题 ID、图片顺序和 Schema 校验通过。原始 OCR 保留不改，复核更正使用 `json/manual/fixups.json` 覆盖层。

正式 PDF 位于 `output/pdf/`：

- `澄潇宇大观题库-多元积分·无空版.pdf`：58 页，正文 54 页。
- `澄潇宇大观题库-多元积分·留空版.pdf`：80 页，正文 76 页。
- `交付校验报告.json`：题数、页数、目录书签、SHA-256 与编译检查。

两版均收录 391 道题，有封面、封二、目录和封底；保留题号、题源与 3 张题干配图，仅排题目和选项。正文页脚总页数不计封面、封二、目录和封底。留空版加大题间演算空间，无空版紧凑排版。

6 道标记题已逐题核对：3 道文字层冲突的 OCR 正确；一道方向导数题仅补填写空线；一道缺失的第二问依据本地《李艳芳900题》A4做题本 PDF 第311页原题图补齐。另一道源图只有三重积分式，保留其原式，不补写源图没有的作答文字；原始 needs_review 标记保留可追溯。

全部题号与 manifest 顺序一致，0 缺字、0 公式溢出、0 未定义引用。两版全页经 Poppler 渲染总览检查，重点复核封面、封二、公式、图形和补齐题；分类标题与首题、图形与题干保持同页。

可编辑正文、封皮及编译日志在 `tex/`。自包含工具和模板在 `tools/typeset/`，从本目录重建：

```powershell
python .\tools\typeset\build_books.py
python .\tools\typeset\compile_books.py
python .\tools\typeset\verify_books.py
```

需要 XeLaTeX、Python、Pillow；校验另需 PyMuPDF 与 jsonschema。封皮采用微软雅黑与宋体，避免本机可变 Noto 字体的 PDF 驱动兼容问题。重新生成会覆盖生成的 TeX/PDF；人工更正请改覆盖层或构建脚本。
