# local-code-review

[![demo](https://github.com/weiping/local-code-review/actions/workflows/demo.yml/badge.svg)](https://github.com/weiping/local-code-review/actions/workflows/demo.yml)
[![ai-review](https://github.com/weiping/local-code-review/actions/workflows/ai-review.yml/badge.svg)](https://github.com/weiping/local-code-review/actions/workflows/ai-review.yml)

`review.py` 是一个在自己机器上运行的 AI 代码审查脚本，单文件、只用 Python 标准库，共 378 行（以 `wc -l` 为准）。它通过 OpenAI 兼容的 chat completions 接口调用模型（默认是本机的 [Magpie](https://github.com/yetone/magpie) 网关 `http://127.0.0.1:3425/v1`），模型发出的每条命令都在 Anthropic 的 [sandbox-runtime](https://github.com/anthropics/sandbox-runtime)（srt）里跑。模型先跑代码确认 bug，再以补丁形式给出修复；补丁不进沙箱，加 `--apply` 才写回工作区。

博客正文《给 AI 代码审查配一个能跑代码的沙箱》讲设计和取舍，本仓库是配套代码和测试。改编自 OpenRouter 官方博客 [Build an AI Code Reviewer with OpenRouter (Python)](https://openrouter.ai/blog/tutorials/ai-code-review/)（2026-11-01）。

| 文件 | 用途 |
| --- | --- |
| `review.py` | 审查脚本 |
| `fake_llm.py` | 按剧本返回工具调用的假模型服务。剧本里的检查命令会在 srt 沙箱里真跑，只有"判断"是写死的 |
| `run_demo.sh` | 用假模型跑完全部机制用例，逐条判定 PASS/FAIL |
| `fixtures/make_repo.sh` | 生成示例仓库：先提交一个干净版本，再在工作区留下 5 个埋点 bug，外加一个重命名后又修改的文件、一个约 288 KiB 只改了一行的数据文件、一个未跟踪的新文件 |
| `fixtures/pre-push` | pre-push 钩子：只审查这次要推送的提交，退出码 1 和 2 都会阻止推送（`AI_REVIEW_ON_INCOMPLETE=warn` 时 2 只警告）。仓库根目录有 `.env` 就自动加载（`LLM_BASE_URL`、`AI_REVIEW_MODEL`、`AI_REVIEW_CONTEXT`、`AI_REVIEW_ON_INCOMPLETE`），格式见 `.env.example`。本机安装：`cp fixtures/pre-push .git/hooks/pre-push && chmod +x .git/hooks/pre-push` |
| `realmodel/run_real.sh`、`realmodel/oracle.py` | 真实模型实测：在示例仓库上跑 N 次，`--apply` 后用 oracle 在宿主机上逐一检查五个 bug 是否修好 |
| `realmodel/analyze.py` | 从报告里统计 token、发现，以及 `run_shell` 里有几条真的执行了代码 |
| `realmodel/results-srt-glm/`、`realmodel/results-srt-kimi/` | Mac mini M4 上经 Magpie 接入 `auto/glm-5.3`、`kimi-code-cn/k3.1-pro` 各跑 3 次的报告和汇总。云端模型，代码会发到服务商 |
| `demo-results-macos-srt.txt`、`demo-results-macos-srt-py39.txt` | macOS 27.2（Mac mini M4）上 `run_demo.sh` 的完整输出，`review.py` 分别用 Python 3.14.3 和系统自带的 3.9.6 运行 |
| `demo-results-macos-no-sandbox.txt` | 同一台 Mac 上 `run_demo.sh no-sandbox` 的输出（CI 用的模式） |
| `demo-results-linux-srt.txt` | Debian 13 容器（内核 6.12，x86_64，bubblewrap 0.12.0）上 `run_demo.sh` 的完整输出，Python 3.13.5 |
| `.github/workflows/demo.yml` | 本仓库的 CI：在 GitHub 托管的 `ubuntu-latest` 上用假模型跑 `run_demo.sh no-sandbox`，再用 act 跑 `ci/run_ci_demo.sh`。不装 srt，不用 secret，不调真实模型 |
| `.github/workflows/ai-review.yml` | 本仓库已启用的 PR 真审查：直连智谱 GLM-5.3（需配 `vars`/`secrets`），`--no-sandbox`，只审同仓库 PR，脚本取自基准提交的根目录 `review.py` |
| `ci/ai-review.yml` | 给其他仓库拷贝的 portable 模板（约定 `tools/review.py`）；本仓库的 live 副本在 `.github/workflows/ai-review.yml` |
| `ci/run_ci_demo.sh` | 用 act 在本机按 `pull_request` 事件跑这个 workflow 的 7 项检查 |
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

已知限制：

- 补丁不进沙箱，模型只能针对原始代码做检查；补丁对不对，要在 `--apply` 之后用你自己的测试验证。
- 模型在沙箱里用 `run_shell` 改动或删除的文件不会进入补丁。
- `/usr`、`/etc` 这类系统目录在沙箱里仍然可读。
- 使用 `--head` 时，`--context` 指定的文件从工作区读取。
- Linux 上的 srt 只在一个 Debian 13 容器里测过（容器允许无特权用户命名空间，不需要 `--nested-sandbox`），没在 Ubuntu 和实体机上测过；Windows 没有测过。
- Linux 上 srt 会在每个禁读的目录（如 `/tmp`）上盖一层空的 tmpfs，沙箱里往那里写会成功，但写进的是这层 tmpfs，命令结束就没了，碰不到真实文件。macOS 上则直接拒绝。

## CI

CI 用 GitHub 托管的 `ubuntu-latest`，不装 srt：每个 job 都是一台新开、用完即销毁的虚拟机，job 里只有只读的 `GITHUB_TOKEN`，所以 `review.py` 用 `--no-sandbox` 直接在 runner 上跑命令。只有 srt 才成立的限制类用例在本机的 `bash run_demo.sh` 里测。

本仓库的 `.github/workflows/demo.yml` 只用假模型：不调真实模型、不需要 secret。真实 PR 审查已启用为 `.github/workflows/ai-review.yml`（由 `ci/ai-review.yml` 拷入，并改为读取根目录 `review.py`）。`ci/ai-review.yml` 仍是给其他仓库拷贝的 portable 模板（约定 `tools/review.py`）。

真实审查需要 OpenAI 兼容且支持 `tool_calls` 的地址。官方文档里 GitHub Copilot 接入 Actions 的方式是 Copilot CLI（或 Agentic Workflows / Copilot SDK）：prompt 进、文本或 agent 出，**不是**给自定义脚本用的 `/v1/chat/completions` + 多轮 `tool_calls`，因此不能满足本仓库的 `review.py`。GitHub Models 也已于 2026-07-30 退役。见 [Using Copilot CLI in GitHub Actions](https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli-in-actions)、[Server-to-server authentication](https://docs.github.com/en/copilot/how-tos/copilot-sdk/auth/server-to-server-tokens)。

CI 改为直连智谱 [GLM-5.3](https://docs.bigmodel.cn/cn/guide/models/text/glm-5.3) 的 OpenAI 兼容接口（[文档](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)）：

| 配置 | 值 |
| --- | --- |
| `vars.LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` |
| `vars.AI_REVIEW_MODEL` | `glm-5.3` |
| `secrets.LLM_API_KEY` | 智谱开放平台 API Key |

本仓库已启用 `.github/workflows/ai-review.yml`（读根目录 `review.py`）。其他仓库仍按模板：拷 `ci/ai-review.yml` 到 `.github/workflows/ai-review.yml`，并把 `review.py` 放到 `tools/review.py`。`--no-sandbox` 下模型的命令能读到这个 job 能读的一切，包括进程里的模型密钥，也能联网；job 只给 `contents: read`。本机开发仍可用 Magpie（例如 `auto/glm-5.3`），与 CI 直连智谱互不冲突。
