# local-code-review

[![demo](https://github.com/weiping/local-code-review/actions/workflows/demo.yml/badge.svg)](https://github.com/weiping/local-code-review/actions/workflows/demo.yml)
[![ai-review](https://github.com/weiping/local-code-review/actions/workflows/ai-review.yml/badge.svg)](https://github.com/weiping/local-code-review/actions/workflows/ai-review.yml)

`review.py` 是一个在自己机器上运行的 AI 代码审查脚本，单文件、只用 Python 标准库，共 386 行（以 `wc -l` 为准）。它通过 OpenAI 兼容的 chat completions 接口调用模型（默认是本机的 [Magpie](https://github.com/yetone/magpie) 网关 `http://127.0.0.1:3425/v1`），模型发出的每条命令都在 Anthropic 的 [sandbox-runtime](https://github.com/anthropics/sandbox-runtime)（srt）里跑。模型先跑代码确认 bug，再以补丁形式给出修复；补丁不进沙箱，加 `--apply` 才写回工作区。

博客正文《给 AI 代码审查配一个能跑代码的沙箱》讲设计和取舍，本仓库是配套代码和测试。改编自 OpenRouter 官方博客 [Build an AI Code Reviewer with OpenRouter (Python)](https://openrouter.ai/blog/tutorials/ai-code-review/)（2026-11-01）。

| 文件 | 用途 |
| --- | --- |
| `review.py` | 审查脚本 |
| `fake_llm.py` | 按剧本返回工具调用的假模型服务。剧本里的检查命令会在 srt 沙箱里真跑，只有"判断"是写死的 |
| `run_demo.sh` | 用假模型跑完全部机制用例，逐条判定 PASS/FAIL |
| `fixtures/make_repo.sh` | 生成示例仓库：先提交一个干净版本，再在工作区留下 5 个埋点 bug，外加一个重命名后又修改的文件、一个约 288 KiB 只改了一行的数据文件、一个未跟踪的新文件 |
| `fixtures/pre-push` | pre-push 钩子：只审查这次要推送的提交，退出码 1 和 2 都会阻止推送（`AI_REVIEW_ON_INCOMPLETE=warn` 时 2 只警告）。仓库根目录有 `.env` 就自动加载（`LLM_BASE_URL`、`AI_REVIEW_MODEL`、`AI_REVIEW_CONTEXT`、`AI_REVIEW_ON_INCOMPLETE`），格式见 `.env.example`。本机验证过三条路径：clean 放行、confirmed medium 放行、confirmed high 拦下推送。本机安装：`cp fixtures/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push` |
| `.env.example` | `.env` 的模板：复制到仓库根目录改名 `.env`（已 gitignore），hook 自动加载 |
| `realmodel/run_real.sh`、`realmodel/oracle.py` | 真实模型实测：在示例仓库上跑 N 次，`--apply` 后用 oracle 在宿主机上逐一检查五个 bug 是否修好 |
| `realmodel/analyze.py` | 从报告里统计 token、发现，以及 `run_shell` 里有几条真的执行了代码 |
| `realmodel/results-srt-glm/`、`realmodel/results-srt-kimi/` | Mac mini M4 上经 Magpie 接入 `auto/glm-5.3`、`kimi-code-cn/k3.1-pro` 各跑 3 次的报告和汇总。云端模型，代码会发到服务商 |
| `realmodel/results-convergence/summary.json` | 18 个模型在「本仓库配置类 diff」与「5-bug 基准仓库」两个场景上的收敛性跑分（n=1 每格），见下文「模型选型」 |
| `edit-eval/` | 编辑格式评测器：固定模型和提示词，只换编辑格式（官方 V4A vs 精确 SEARCH/REPLACE）和 API 协议（OpenAI Chat / Responses / Anthropic Messages），配对比较 12 道题的编辑准确度。原始记录在 `edit-eval/results/results.jsonl`，见下文「V4A 与 old_str/new_str 的编辑准确度对比」 |
| `demo-results-macos-srt.txt`、`demo-results-macos-srt-py39.txt` | macOS 27.2（Mac mini M4）上 `run_demo.sh` 的完整输出，`review.py` 分别用 Python 3.14.3 和系统自带的 3.9.6 运行 |
| `demo-results-macos-no-sandbox.txt` | 同一台 Mac 上 `run_demo.sh no-sandbox` 的输出（CI 用的模式） |
| `demo-results-linux-srt.txt` | Debian 13 容器（内核 6.12，x86_64，bubblewrap 0.12.0）上 `run_demo.sh` 的完整输出，Python 3.13.5 |
| `.github/workflows/demo.yml` | 本仓库的 CI：在 GitHub 托管的 `ubuntu-latest` 上用假模型跑 `run_demo.sh no-sandbox`，再用 act 跑 `ci/run_ci_demo.sh`。不装 srt，不用 secret，不调真实模型 |
| `.github/workflows/ai-review.yml` | 本仓库已启用的 PR 真审查：直连 Kimi K3.1 Pro（需配 `vars`/`secrets`），`--no-sandbox`，只审同仓库 PR，脚本取自基准提交的根目录 `review.py`。有阻断发现（退出码 1）或审查未完成（退出码 2）时 job 失败 |
| `ci/ai-review.yml` | 给其他仓库拷贝的 portable 模板（约定 `tools/review.py`）；本仓库的 live 副本在 `.github/workflows/ai-review.yml` |
| `ci/run_ci_demo.sh` | 用 act 在本机按 `pull_request` 事件跑这个 workflow 的 8 项检查 |
| `archive/v1-docker/` | 上一版脚本（docker/podman/bwrap 后端）的测试记录，只作对照 |

## 前置条件

- macOS 或 Linux，Python 3.9 或更高版本（macOS 自带的 3.9.6 可用），Git，Node.js 22.12 或更高版本（srt 0.0.81 的 `engines` 要求；Debian 13 自带的 20.19、Ubuntu 24.04 自带的 18.19 都不够，用 NodeSource 或 nvm 装）。
- srt：`npm install -g @anthropic-ai/sandbox-runtime@0.0.81`。srt 是 Beta 研究预览，配置格式可能变化，建议固定版本。
- macOS 还要 ripgrep：`brew install ripgrep`。
- Linux 还要 bubblewrap、socat、ripgrep：`sudo apt-get install bubblewrap socat ripgrep`。Ubuntu 24.04 及以上还要 `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`；Debian 没有这个参数，不用设。
- 演示里有两例要连 pypi.org（测 `--allow-domain`），需要联网。
- Windows 没有测过。

## 跑演示

```sh
bash run_demo.sh                      # 解压后若丢失执行权限，用 bash 调用即可
PY=/usr/bin/python3 bash run_demo.sh  # 用别的 Python 运行 review.py，比如 macOS 自带的 3.9.6
```

演示会在你的 `$HOME`、系统临时目录和 `/tmp` 下各放一个临时的 canary 文件，确认沙箱读不到也写不了，跑完删掉。

## 接真实模型

在仓库根目录或任意子目录下运行：

```sh
export LLM_BASE_URL="http://127.0.0.1:3425/v1"   # Magpie，也是默认值；任何 OpenAI 兼容地址都行
python3 /path/to/review.py --model <提供方/模型名> --context tests/test_orders.py --lang 中文
```

复测：`bash realmodel/run_real.sh <模型名> 3`，结果写到 `realmodel/results/`（用 `OUT=目录` 改）。再用 `python3 realmodel/analyze.py <目录>/run-*.json` 看每次真正执行了几条代码。

模型必须真的会调工具：发一条带工具的最小请求，返回里要有 `tool_calls`（博客正文有示例命令）。

常用参数：

- `--allow-domain HOST`（可重复，支持 `*.example.com`）：经 srt 的白名单代理放行指定域名，默认断网。放行的域名解析到私有地址时会被拒绝。
- `--nested-sandbox`：srt 本身跑在容器里时用，启用 srt 较弱的嵌套模式（未测）。
- `--no-sandbox`：不用 srt，命令直接在本机跑，会打印警告。只用在 GitHub 托管 runner 这类用完即弃的机器上，见下文 CI。
- `--shell-timeout`（默认 120 秒，最多 300）、`--max-output`（默认 16384 字符，最多 65536）。
- `--block-at`、`--block-unconfirmed`、`--no-inline-diff`、`--no-untracked`、`--head`、`--apply`、`--output`。

退出码：0 表示通过；1 表示有阻断级发现（默认只算 `confirmed=true` 且 severity 为 high 的）；2 表示没有完成，包括 git、srt、网络等各类错误，以及收到 SIGTERM（退出前会停掉正在跑的沙箱命令，并删掉临时目录）。

轮数用尽前会提醒模型收尾：只剩 3 轮时（`WRAP_UP_TURNS`）插一句「停止再查，现在调用 submit_review」。没有这一步，有些模型会把 20 轮全花在跑检查上，最后既没结论也没退出码（实测 `deepseek-v4-pro`、`auto/glm-5.3`、`auto/minimax-m3` 都会这样）。代价是模型也可能用一份空 findings 交卷——那表示「没发现问题」而不是「没审完」，两者的区别要看报告里的轮数（`realmodel/analyze.py` 会统计 `run_shell` 次数和轮数）。

已知限制：

- 补丁不进沙箱，模型只能针对原始代码做检查；补丁对不对，要在 `--apply` 之后用你自己的测试验证。
- 模型在沙箱里用 `run_shell` 改动或删除的文件不会进入补丁。
- `/usr`、`/etc` 这类系统目录在沙箱里仍然可读。
- 使用 `--head` 时，`--context` 指定的文件从工作区读取。
- Linux 上的 srt 只在一个 Debian 13 容器里测过（容器允许无特权用户命名空间，不需要 `--nested-sandbox`），没在 Ubuntu 和实体机上测过；Windows 没有测过。
- Linux 上 srt 会在每个禁读的目录（如 `/tmp`）上盖一层空的 tmpfs，沙箱里往那里写会成功，但写进的是这层 tmpfs，命令结束就没了，碰不到真实文件。macOS 上则直接拒绝。

## V4A（apply_patch）与 old_str/new_str 的编辑准确度对比

[apply_patch](https://developers.openai.com/api/docs/guides/tools-apply-patch)（V4A diff 格式）的内置工具只对 OpenAI 自家 GPT-5/6 系模型开放；kimi/glm 等非 OpenAI 模型只能把它降级为普通 function tool 或纯文本协议。我们用两轮评测实测了两种格式在非 OpenAI 模型上的编辑准确度。

### 第一轮：手写模糊匹配器（已推翻）

最初用自写的"相似度 ≥0.9 模糊匹配"解析器测得 V4A 大量静默改错（改错位置但工具报成功），后来发现那是解析器的 bug，不是 V4A 的：OpenAI 官方实现（openai-agents-python 的 `apply_diff.py`）对上下文行做**精确 → rstrip → strip** 三级匹配，幻觉上下文会响亮报错 `Invalid Context`，不会静默通过。

### 第二轮：官方解析器 + 三协议配对实验

搭了配对实验（固定模型 `kimi-code-cn/k3.1-pro`，同一题同一初始文件，两种格式各跑一遍），在 Magpie 网关的三种 API 协议下测试。执行器：V4A = 严格外层文法 + 官方 `apply_diff.py`；SEARCH/REPLACE = 严格执行器（逐字匹配、恰好一次、失败回滚）。每格跑 3 次，最多一次修正。

**12 道题**分五类：简单局部修改 ×3、重复代码中指定修改 ×3、缩进/空行/EOF ×3、单文件多处 ×2、跨两文件 ×1。每题都验证初始代码失败、参考实现通过。共 432 格（12 题 × 3 协议 × 2 格式 × 2 阶段 × 3 重复），全部有效响应、零接口错误。

| API 协议 | 格式 | 纯文本阶段首次/最终 | 工具调用阶段首次/最终 |
| --- | --- | --- | --- |
| OpenAI Chat Completions | SEARCH/REPLACE | **100% / 100%** | 67% / **100%** |
| | V4A | **100% / 100%** | 50% / 92% |
| OpenAI Responses | SEARCH/REPLACE | **100% / 100%** | 72% / 97% |
| | V4A | **100% / 100%** | 56% / 92% |
| Anthropic Messages | SEARCH/REPLACE | **100% / 100%** | 75% / **100%** |
| | V4A | **100% / 100%** | 50% / **100%** |

**结论**：

1. **纯文本阶段 V4A 与 SR 完全打平**（三协议均 100%）：官方解析器对幻觉上下文会响亮报错，不再静默改错。两种格式都能准确表达编辑。
2. **工具调用阶段唯一的失败原因是协议不合规**：432 格里 83 次失败全部是"模型把补丁写成纯文本而没调用工具"（或调了多次），没有一次是格式内容错误、锚定失败或歧义匹配。这与格式无关，两种格式都犯，V4A 略多一些（首次合规率 50%～56% vs SR 的 67%～75%），重试一次后大多修复。
3. **按题看（合并 18 格/题）**：12 题里 10 题两种格式都是全对；V4A 略弱的 3 题是 `a2-default-param`（16/18）、`c1-eof-version`（16/18）、`c3-blank-lines`（17/18），共同点是 V4A 要求上下文行带空格前缀，模型偶尔漏写——这是格式细节而非锚定缺陷。
4. **SEARCH/REPLACE 的唯一性检查**（`old_str` 出现 0 次或多次就报错退回模型）把歧义变成响亮、可重试的错误，模型在重复代码场景全对。

**为什么不换 V4A**：纯文本阶段无差异；工具调用阶段 SR 首次合规率更高、重试更少；V4A 对上下文行的空格前缀更严格，模型偶有漏写；且 OpenAI 系模型的内置 V4A 工具在 Magpie 网关上无法使用（只对 OpenAI 官方 API 开放）。现有 `edit_file` + `create_file` + `delete_file` 保持不变。若审查模型换成 OpenAI 系且直连 OpenAI API，内置 apply_patch 才值得重议。

## 模型选型（18 个模型实测）

两个基准场景各跑一次（`--max-turns 20`，n=1 每格，数字作指示性参考）：

> 表里的「❌ 跑满 20 轮不交卷」是加收尾提醒**之前**的结果。这些模型现在会被提醒交卷，但交卷质量仍需自己判断（空 findings 还是真结论，看报告里的轮数）。

- **场景 A**：本仓库的配置/工作流 diff（5 个文件，`--no-sandbox`）——这类没有代码可跑的 diff 最容易让推理模型陷入死循环翻目录。
- **场景 B**：`fixtures/make_repo.sh` 的 5-bug 基准仓库（srt 沙箱、`--context tests/test_orders.py`、`--apply`），补丁由 `realmodel/oracle.py` 在宿主机逐一验证。

| 模型（Magpie id） | 场景 A | 场景 B | tokens (A+B) | 耗时 (A+B) |
| --- | --- | --- | --- | --- |
| `anthropic/claude-opus-5-5` | ✅ 5 轮，1 条 confirmed high，带补丁 | ✅ 4 轮，5 条 confirmed，oracle **5/5** | 61k | 63s |
| `auto/gemini-4-argon` | ✅ 4 轮，判定通过 | ✅ 7 轮，4 条 confirmed，oracle **5/5** | 55k | 124s |
| `auto/gpt-6.1-terra` | ✅ 7 轮，1 条 confirmed high，带补丁 | ✅ 8 轮，6 条 confirmed，oracle **5/5** | 111k | 339s |
| `kimi-code-cn/k3.1-pro` | ✅ 9 轮，1 条 confirmed high | ✅ 8 轮，5 条 confirmed，oracle **5/5** | 168k | 465s |
| `kimi-code-cn/kimi-for-coding`（K2.8） | ✅ 11 轮，判定通过 | ✅ 8 轮，5 条 confirmed，oracle **5/5** | 136k | 362s |
| `auto/grok-4.7` | ⚠️ 第 20 轮踩线交卷，2 条 confirmed high | ✅ 10 轮，5 条 confirmed，oracle **5/5** | 667k | 502s |
| `auto/glm-5.3` | ❌ 跑满 20 轮不交卷 | ✅ 10 轮，4 条 confirmed，oracle **5/5** | 314k | 940s |
| `auto/glm-5.3-flash` | ❌ 跑满 20 轮不交卷 | ✅ 11 轮，5 条 confirmed，oracle **5/5** | 373k | 1060s |
| `auto/minimax-m3` | ❌ 跑满 20 轮不交卷 | ✅ 15 轮，6 条 confirmed，oracle **5/5** | 977k | 445s |
| `qoder-cn/qfmodel`（Qwen3.8-Flash） | ❌ 网关 >900s 无响应 | ✅ 17 轮，6 条 confirmed，oracle **5/5** | 140k | 452s+ |
| `anthropic/claude-sonnet-5-5` | ✅ 2 轮，1 条 unconfirmed | ⚠️ 4 轮，4 条 confirmed 但**不调 edit_file**（0/5） | 26k | 36s |
| `anthropic/claude-haiku-5-5` | ✅ 4 轮，1 条 confirmed medium | ⚠️ 7 轮，4 条 confirmed 但**不调 edit_file**（0/5） | 75k | 58s |
| `auto/gpt-6-luna` | ✅ 6 轮，1 条 confirmed high | ⚠️ 6 轮，4 条 confirmed 但**不调 edit_file**（0/5） | 71k | 120s |
| `cursor/composer-2.5` | ❌ 429 限流 | ⚠️ 6 轮，4 条 confirmed 但**不调 edit_file**（0/5） | 24k | 79s |
| `auto/gemini-3.8-flash` | ✅ 12 轮，判定通过 | ❌ 跑满 20 轮不交卷 | 175k | 104s |
| `auto/deepseek-v4-pro` | ❌ 跑满 20 轮不交卷 | ❌ 跑满 20 轮不交卷 | 345k | 365s |
| `deepseek/deepseek-flash`（V4.1-Flash） | ❌ 跑满 20 轮不交卷 | ❌ 跑满 20 轮不交卷（6 次 edit_file 但 0 次 submit） | 597k | 784s |
| `qoder-cn/qmodel_38max`（Qwen3.8-Max） | ❌ 网关 >900s 无响应 | ❌ 跑满 20 轮不交卷 | 176k | 793s+ |
| `auto/claude-sonnet-5-5`、`auto/claude-opus-5-5` | — | — | — | ⚠️ 这两个自定义路由组未包含 `anthropic/...` 成员：opus 会 429（Cursor/Antigravity 配额耗尽），sonnet 走 Cursor/Copilot 时表现为 2～3 轮过快交卷、0 confirmed |

三个行为模式：

1. **收敛 ≠ 修好**。Claude Sonnet/Haiku、GPT-6 Luna、Composer 2.5 交卷很快（2～7 轮），也真跑代码实锤了 bug，但常常漏调 `edit_file` 给补丁——作门禁（只看 findings）没问题，`--apply` 自动修复时会漏。
2. **DeepSeek 全系不写 `submit_review`**：V4-Pro 把 5 个 bug 各写了验证脚本反复测，就是一直不交卷；V4.1-Flash 连补丁都写了 6 份也不交卷。
3. **配置/文档类 diff 是照妖镜**：GLM-5.3、GLM-5.3-Flash、MiniMax-M3 遇到没有代码可跑的 diff 会反复翻目录到 20 轮烧完（MiniMax-M3 单次 74 万 tokens）。

**选型建议**：

- **本机（经 Magpie）**：首选 `kimi-code-cn/k3.1-pro`（本仓库 `.env` 的现值）；要更快更省换 `kimi-code-cn/kimi-for-coding`（K2.8，5/5 全修且 tokens 最省）；要质量上限用 `anthropic/claude-opus-5-5`（4～5 轮、15～45k tokens、5/5 全修，但烧 Anthropic API 余额）；`auto/gemini-4-argon`、`auto/gpt-6-1-terra` 也是可靠备选。
- **CI（需静态 key + OpenAI 兼容端点）**：只有 Kimi Code 端点同时满足「直连 + 稳定收敛」，即现配置 `k3.1-pro` @ `https://api.kimi.com/coding/v1`；同端点把 `vars.AI_REVIEW_MODEL` 换成 `kimi-for-coding` 可再省一半 token。其余渠道（Copilot/Cursor/Anthropic 账号）走 OAuth 登录态，CI 里用不了。
- **别用**：`auto/deepseek-*` 全系（不调 `submit_review`）、Qoder CN 渠道（网关延迟高到超时）、以及场景 A 会发散的模型作 CI 门禁（glm-5.3 系、minimax-m3）。

原始逐轮数据在 `realmodel/results-convergence/summary.json`（每个模型含轮数、各工具调用次数、token、耗时、oracle 明细）。

## CI

CI 用 GitHub 托管的 `ubuntu-latest`，不装 srt：每个 job 都是一台新开、用完即销毁的虚拟机，job 里只有只读的 `GITHUB_TOKEN`，所以 `review.py` 用 `--no-sandbox` 直接在 runner 上跑命令。只有 srt 才成立的限制类用例在本机的 `bash run_demo.sh` 里测。

本仓库的 `.github/workflows/demo.yml` 只用假模型：不调真实模型、不需要 secret。真实 PR 审查已启用为 `.github/workflows/ai-review.yml`（由 `ci/ai-review.yml` 拷入，并改为读取根目录 `review.py`）。`ci/ai-review.yml` 仍是给其他仓库拷贝的 portable 模板（约定 `tools/review.py`）。

真实审查需要 OpenAI 兼容且支持 `tool_calls` 的地址。官方文档里 GitHub Copilot 接入 Actions 的方式是 Copilot CLI（或 Agentic Workflows / Copilot SDK）：prompt 进、文本或 agent 出，**不是**给自定义脚本用的 `/v1/chat/completions` + 多轮 `tool_calls`，因此不能满足本仓库的 `review.py`。GitHub Models 也已于 2026-07-30 退役。见 [Using Copilot CLI in GitHub Actions](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions)、[Server-to-server authentication](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/server-to-server-tokens)。

CI 改为直连 [Kimi K3.1 Pro](https://www.kimi.com/code) 的 OpenAI 兼容接口：

| 配置 | 值 |
| --- | --- |
| `vars.LLM_BASE_URL` | `https://api.kimi.com/coding/v1` |
| `vars.AI_REVIEW_MODEL` | `k3.1-pro` |
| `secrets.LLM_API_KEY` | Kimi Code 套餐 Key（`sk-k…`） |

多模型收敛性对比见上文「模型选型」：同为 Kimi Code 端点的 `kimi-for-coding`（K2.8）也 5/5 修好基准 bug 且 tokens 最省；GLM-5.3、`auto/kimi-k3` 遇到没有代码可跑的 diff 会 20 轮跑满不提交。

模型兼容：有的端点只接受一个 temperature（Kimi 只收 1），`review.py` 遇到 400 且报文提到 temperature 会自动改用 1 重试该轮。

本仓库已启用 `.github/workflows/ai-review.yml`（读根目录 `review.py`）。其他仓库仍按模板：拷 `ci/ai-review.yml` 到 `.github/workflows/ai-review.yml`，并把 `review.py` 放到 `tools/review.py`。`--no-sandbox` 下模型的命令能读到这个 job 能读的一切，包括进程里的模型密钥，也能联网；job 只给 `contents: read`。本机开发仍可用 Magpie（例如 `auto/glm-5.3`），与 CI 直连厂商互不冲突。
