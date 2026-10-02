# OCR-AI 工作说明

本目录定义“题图 → 结构化中文与 LaTeX”的输入、提示词和输出格式。

## 文件

- `prompt.md`：直接发送给 OCR-AI 的完整提示词，包含固定指令和逐题消息模板。
- `output.schema.json`：OCR 结果的 JSON Schema，用于程序校验。

## 调用约定

1. 从根目录 `manifest.json` 逐题读取数据。
2. 一次只处理一道题；按 `images.question` 的顺序附加该题全部图片。
3. 把题目的元数据填入 `prompt.md` 末尾的“逐题用户消息模板”。
4. 结果保存为 `json/ocr/question/<item_id>.json`，UTF-8 编码。
5. 已存在且通过 Schema 校验的结果默认跳过，便于断点续跑。
6. `img/related/` 不随题目 OCR 一起发送；它需要先人工或程序分类，再作为答案 OCR 的独立输入。

OCR-AI 的职责只是忠实转写，不负责解题、纠错或补全题意。

