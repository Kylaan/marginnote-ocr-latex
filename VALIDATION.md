# 实际交付验证记录

日期：2026-10-02。以下是在本机 `ForGit` 实例上实际执行的结果。

## 环境

- Python 3.13，Pillow 12.0.0，jsonschema 4.25.1，PyMuPDF 1.27.2.3。
- 本机 TeX Live 2025 / XeLaTeX；Windows 默认字体配置。
- Git 2.51.0.windows.1，Git LFS 3.7.0。

## 数据和有效状态

- 原始数据库、915 张图像、391 个 OCR JSON 与原交付保持一致。
- 原始 OCR 状态 385 `ok` / 6 `needs_review`，不抹除模型原始疑点。
- 7 条人工覆盖，依据已有核图记录关闭已解决状态和裁切/缺上下文标记，保护原有微元更正；覆盖后 391 `ok`。
- Schema、qid/item_id/seq 唯一性、OCR 集合覆盖和输入图片顺序通过。
- 数据库 integrity_check、SHA-256、目录树顺序、图像解码、逐张载荷一致性通过。
- 本地证据路径可解析；第二问补齐证据使用仓库内图片。

## 真实重建

已在 `ForGit` 执行 `build_books.py` 和 `compile_books.py`，成功编译两套封皮与正文，并通过 PDF 校验。

| 版本 | 物理页 | 正文页 | 题数 |
|---|---:|---:|---:|
| 无空版 | 58 | 54 | 391 |
| 留空版 | 80 | 76 | 391 |

两版题号与 manifest 顺序一致；章节书签、目录、页脚、配图位置检查通过。编译日志无 Missing character、Overfull 或 undefined 引用。

以 PyMuPDF 72 dpi RGB 渲染新旧 PDF 的全部 138 页，逐页比较宽高和像素 SHA-256：**138 页全部像素一致**。PDF 文件哈希因重新编译元数据变化而更新，不用旧二进制哈希冒充新文件。该比对证明本次整理没有改变历史版面，不代表重新逐题审读全部公式。

## 六项离线测试

`python -m unittest discover -s tests -v`：6 项全部通过。

1. 互不重叠分片、重复候选拒绝与有效合并。
2. 图片转写顺序错误拒绝。
3. 已有合格结果无需配置或密钥即可断点跳过。
4. 模拟 HTTP 首次非法 JSON、重试成功；人工覆盖字节保持不变。
5. 不确定公式标记自动降为 `needs_review`。
6. 模型返回错误 ID 时拒绝写入，并保留既有正式结果。

测试只使用本地 HTTP 模拟服务与临时题目，不调用实际 OCR 提供商。GitHub Actions 提供同一套测试工作流，尚未在远程执行。

## 上传准备

- 常见 token / 明文密码匹配扫描覆盖现行文本和两个 ZIP 内文本，未发现匹配；OCR 交付历史说明中的密码已移除。
- 两个历史 ZIP CRC 与归档 SHA-256 检查通过；原始拆包 ZIP 保持原字节，OCR 快照脱敏重打包。
- 在临时 Git 仓库用真实 `git check-attr` 核对 1274 个二进制路径，均得到 `filter=lfs`；本机配置、密钥文件、虚拟环境、运行目录与重复 job PDF 的忽略规则通过。
- 交付数据与历史归档保留后，目录约 1.04 GiB；超过 100 MiB 的四个文件均有 LFS 规则。
- 原项目没有被修改或移动；`ForGit` 尚未初始化 Git、提交或连接远程。

扫描针对常见凭据模式和文本，不构成数据库中全部个人信息的审查。资料许可说明见 DATA-NOTICE.md；完整实例可先使用私人仓库。

## 机器可读证据

- `work/logs/project-check.json`
- `work/logs/upload-check.json`
- `work/logs/render-comparison.json`
- `work/logs/environment-and-git-rules.json`
- `tex/build-report.json`
- `tex/work/pdf-validation.json`
- `output/pdf/交付校验报告.json`
- `docs/history/archive-inventory.json`
- `docs/history/data-checksums.json`

原始包与源码工具的联网 OCR、Linux/macOS 字体编译和答案工作流未在此次交付执行。
