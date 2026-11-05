# edit-eval：V4A 与 old_str/new_str 的编辑准确度评测

配套仓库根 README 的「V4A（apply_patch）与 old_str/new_str 的编辑准确度对比」一节。

## 做什么

固定一个模型和一套提示词，只换**编辑格式**（V4A 补丁 vs 精确 SEARCH/REPLACE）和 **API 协议**（OpenAI Chat Completions / OpenAI Responses / Anthropic Messages，走 Magpie 网关），配对比较模型能否把编辑改对。

每次运行：

- **配对**：同一道题、同一个初始文件、同一个模型，两种格式各跑一遍，避免把题目难度和模型能力混在一起。
- **两阶段**：`text` 让模型把补丁写在正文里（分别按两种格式解析）；`tool` 让模型调用一个只有一个字符串参数的工具（协议写在工具描述里）。两阶段分开，才能把「格式理解」和「工具调用」区分开。
- **判定**：执行补丁后跑隐藏测试（只有 `PATH` 的子进程，30 秒超时），不看模型说了什么，只看文件最终对不对。
- **最多一次修正**：首次失败时把错误或测试输出退回模型，修改保留在当前状态上继续。
- **记录**：每次尝试一行 JSONL（传输/解析/应用/越权/测试五层结果、失败阶段、token、耗时）。

## 跑

```sh
python3 edit-eval/make_tasks.py                 # 生成任务并自验（初始失败、参考通过）
python3 edit-eval/runner.py --reps 3            # 432 格：12 题 × 3 协议 × 2 格式 × 2 阶段 × 3 重复
python3 edit-eval/summarize.py                  # 汇总：分协议/格式的通过率 + 配对表
bash   edit-eval/run_with_fallback.sh           # 额度满时自动换供应商的同名模型
```

需要 Magpie 网关在 `127.0.0.1:3425`（默认模型 `kimi-code-cn/k3.1-pro`；`--model` 可换）。输出写 `edit-eval/results/runs/`，不会覆盖已入库的基线 `edit-eval/results/results.jsonl`。

## 目录

| 文件 | 用途 |
| --- | --- |
| `make_tasks.py` | 12 道任务的定义与生成器（生成 `tasks/`，含隐藏测试；`tasks/` 不入库） |
| `runner.py` | 评测主程序：三种协议适配器 + 重试 + 判定 + JSONL 记录 |
| `executors/v4a.py` | V4A 执行器：严格外层文法 + 官方 `apply_diff.py` |
| `executors/sr.py` | SEARCH/REPLACE 执行器：逐字匹配、恰好一次、多块按序、失败回滚 |
| `prompts/` | 三种提示词：`common.txt`（共用规则）+ `v4a.txt` / `sr.txt`（各格式协议） |
| `util.py` | 在隔离环境里跑隐藏测试 |
| `summarize.py` | 汇总成通过率表与配对表 |
| `vendor/apply_diff.py` | OpenAI 官方 V4A 解析器（见下） |
| `results/results.jsonl` | 432 格原始记录（对应 README 那张表） |

## vendor/apply_diff.py

来自 [openai/openai-agents-python](https://github.com/openai/openai-agents-python/blob/main/src/agents/apply_diff.py)（MIT），取自 commit `814de8b1cfdaf6c70212dca9ca23563dd0b789ac`，与该 commit 逐字节一致（sha256 前 16 位 `bb2fd2b0f9846ab2`）。

用它而不是自己重写，是因为 V4A 的锚定规则（精确 → rstrip → strip 三级匹配、`@@` 锚点、EOF hunk）细节很多：先自己写过一版「相似度 ≥0.9 模糊匹配」，结果把幻觉上下文当成匹配成功，静默改错位置——那是解析器的 bug，不是 V4A 的。换成官方实现后，同一输入会响亮报 `Invalid Context`。

## 已知口径问题

- 工具阶段要求模型**恰好调一次**工具：把多处修改拆成多次调用会被判 `invalid_format`。生产用的 harness 通常接受多次调用，所以这里的 `invalid_format` 偏严，测的是「协议纪律」而不是「编辑能力」。
- 12 道题每格只跑 3 次，样本小；结论看方向和量级，不做显著性检验。
- 模型在 `text` 阶段的正文可能被网关裁剪，`finish_reason=length` 记为 `output_truncated` 而不是格式失败。
