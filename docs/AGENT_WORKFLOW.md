# Agent / 子 Agent 工作协议

## 主 Agent

1. 阅读 manifest、现行 README、Schema 和覆盖层；检查 ID、图片库存、原始数据库。
2. 根据用户授权决定是否启用子 Agent。使用 `tools/agent_tasks.py plan` 生成互不重叠任务，记录分配；线程 API workers 与子 Agent 不是同一种执行方式。
3. 子 Agent 只写自己的候选目录；统一写入者负责正式 OCR，避免并发覆盖。
4. 收集候选后运行 merge。缺失、重复或不匹配结果必须先修正，不能以空 JSON 填数。
5. 按源图处理 `needs_review`，把每项结论固化为有证据的覆盖层。
6. 执行 check_project，再生成和编译；校验交付 PDF，视觉检查封面、长公式、图形、补齐题和分页。

## 子 Agent 提示词（可复制）

> 处理提供的 shard-XX.json 中全部且仅这些题目。阅读 work/ocr-ai/prompt.md 和 output.schema.json。按每题 images.question 的数组顺序查看原图；raw_text 仅作辨认辅助，冲突时以图像为准。不要阅读 images.related 来补题，不解题、不替原作者纠错。每题输出一个满足 Schema 的 UTF-8 JSON，文件名为 item_id.json，保存到任务规定的独立候选目录。保持 qid/item_id 和 image_transcriptions 的路径顺序完全一致。无法辨认、图被截断或缺上下文时明确标记 needs_review。不得改动 manifest、源图、数据库、正式 OCR 或人工覆盖层。完成时报告处理数量、未解决题目 ID 与原因；不得宣称自己未执行的检查已经通过。

## 复核 Agent 提示词（可复制）

> 核对候选 OCR 与每题全部题图，重点检查积分微元、上下标、范围、方向/侧别、缺失小问和图像顺序。只写候选更正与证据说明，由主 Agent 合入 json/manual/fixups.json。保持原始 OCR 可追溯。外部补齐必须有原题证据，不能从答案推测。报告哪些疑点已解决、哪些仍未解决；不要因为编译成功就认定公式语义正确。

## 唯一性与通过标准

qid/item_id/seq 全局唯一；391 道题的 OCR 结果集合与 manifest 完全相同。按输入题图顺序保存转写。人工覆盖的有效结果必须是 `ok` 且无尚未解决的阻塞标记。目录树、数据库与图像字节检查通过，两版 PDF 题号顺序和当前哈希一致。

图形标记 `contains_diagram`、事实标记 `raw_text_conflict`、源图混有解析的 `possible_answer_content` 可以保留，不应为了消除提示随意删除。混有答案时必须确认 `latex/options` 只包含题目，逐图转写不进入 PDF。语义去重是可选新任务；本流程不自动删同题不同来源。

## 中断恢复

OCR 默认跳过已校验的非失败结果；模型/API 失败写日志，不写伪成功。候选合并先完整预检查，之后逐文件替换；磁盘故障时重新运行同一份已审核候选即可。唯一写入锁位于 runs/writer.lock，只有确认原进程已结束才清除。

历史修订以覆盖层为准，重跑 raw JSON 不得改动覆盖层。复核者需重新检查“覆盖后的题目”与新原始结果是否依然相符；覆盖层保护修订，不代替后续审读。
