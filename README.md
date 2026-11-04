# local-code-review

[![demo](https://github.com/weiping/local-code-review/actions/workflows/demo.yml/badge.svg)](https://github.com/weiping/local-code-review/actions/workflows/demo.yml)

`review.py` 是一个自托管的 AI 代码审查脚本，单文件、只用 Python 标准库，共 452 行（以 `wc -l` 为准）。它通过任何 OpenAI 兼容的 chat completions 接口调用模型，让模型在本机沙箱里实际跑代码，确认 bug 之后再以补丁形式给出修复。补丁不进沙箱，加 `--apply` 才写回工作区。

改编自 OpenRouter 官方博客 [Build an AI Code Reviewer with OpenRouter (Python)](https://openrouter.ai/blog/tutorials/ai-code-review/)（2026-11-01）。【待作者补充：转载/改编授权】

| 文件 | 用途 |
| --- | --- |
| `review.py` | 审查脚本 |
| `fake_llm.py` | 按剧本返回工具调用的假模型服务。剧本里的检查命令会在沙箱里真跑，只有"判断"是写死的 |
| `fixtures/make_repo.sh` | 生成示例仓库：先提交一个干净版本，再在工作区留下 5 个埋点 bug，外加一个重命名后又修改的文件、一个约 288 KiB 只改了一行的数据文件、一个未跟踪的新文件 |
| `fixtures/pre-push` | pre-push 钩子示例：只审查这次要推送的提交；退出码 1 和 2 都会阻止推送（`AI_REVIEW_ON_INCOMPLETE=warn` 时 2 只警告） |
| `fixtures/Dockerfile.deps` | 预装依赖的沙箱镜像示例，配合 `--image`，在断网时使用 |
| `realmodel/run_real.sh`、`realmodel/oracle.py` | 真实模型实测：在示例仓库上跑 N 次，`--apply` 后用 oracle 检查五个 bug 是否修好 |
| `realmodel/analyze.py` | 从报告里统计 token、发现，以及 `run_shell` 里有几条真的执行了代码 |
| `realmodel/results/` | Linux 测试机上 `qwen3:4b-instruct-2507-q4_K_M`（bwrap，CPU）跑 3 次的报告和汇总 |
| `realmodel/results-macos/` | Mac mini M4 上 `qwen2.5-coder:7b`（上下文 32768，docker，Ollama 0.5.12）跑 3 次的报告和汇总 |
| `realmodel/results-macos-14b/` | Mac mini M4 上 `qwen2.5-coder:14b`（上下文 8192，docker）跑 3 次的报告和汇总 |
| `realmodel/results-macos-glm/` | Mac 上经本机网关 Magpie（`http://127.0.0.1:3425/v1`）接入云端 `auto/glm-5.3`（智谱）跑 3 次的报告和汇总。云端模型，代码会发到服务商 |
| `realmodel/pilot/` | 正式测试前用旧版提示词试跑的一次记录 |
| `run_demo.sh` | 一键跑完全部用例并逐条判定 PASS/FAIL |
| `.github/workflows/demo.yml` | 本仓库自己的 CI：在 GitHub 托管的 `ubuntu-latest` 上用假模型跑 `run_demo.sh`，bwrap、docker、podman、unsafe-local 各一个 job，不用 secret、不调真实模型 |
| `ci/ai-review.yml` | GitHub Actions workflow 示例（自托管 runner，只审同仓库 PR，脚本取自基准提交） |
| `ci/run_ci_demo.sh` | 用 act 在本机跑这个 workflow 的 7 项检查 |
| `ci/ci-results-docker.txt`、`ci/ci-results-bwrap.txt` | 第 3 轮修订时在 Linux 上跑 CI 演示的输出 |
| `demo-results-macos.txt` | 定稿时在 macOS（Mac mini M4，Docker Desktop）上的完整输出：docker、unsafe-local、pre-push，Python 3.9.6 和 3.14.3 |
| `demo-results-linux.txt` | 定稿时在 Linux 测试机上的完整输出：bwrap、unsafe-local、pre-push，以及去掉 `timeout` 命令后的 unsafe-local |
| `demo-results-round3-linux.txt` | 第 3 轮修订时在 Linux 上四个后端的完整输出（当时的 review.py） |

## 前置条件

- Linux 或 macOS，Python 3.9 或更高版本（macOS 自带的 3.9.6 可用），Git。
- 至少一个沙箱后端：
  - `bwrap`：只限 Linux，需要 bubblewrap，且系统允许无特权用户命名空间。
  - macOS：用 `docker` 后端（Docker Desktop，实测 28.1.1）。macOS 上 `--allow-domain` 不可用（Docker Desktop 不能把宿主机的 unix socket 传进容器，脚本会以 2 退出并说明），需要依赖时用 `--image`。
  - `docker` / `podman`：需要对应程序，首次运行会拉取 `docker.io/library/python:3.12-slim`（离线环境要先准备好）。在 Linux 上，演示里这两个后端各有一例要连 pypi.org（测 `--allow-domain`）；还会构建 `fixtures/Dockerfile.deps`。
- 跑演示不需要真实模型。
- Windows 没有测过；macOS 上的 podman、colima、OrbStack 没有测过。

## 跑演示

```sh
bash run_demo.sh                           # 默认跑 unsafe-local 和 bwrap（解压后若丢失执行权限，用 bash 调用即可）
bash run_demo.sh bwrap docker podman       # 指定后端（Linux）
bash run_demo.sh docker unsafe-local       # macOS
PY=/path/to/python3.9 bash run_demo.sh bwrap  # 用别的 Python 版本运行 review.py
```

`unsafe-local` 后端没有任何隔离。演示里它只执行三类操作：读取示例仓库、打印 `$HOME`、尝试连一次 example.com:80，用来说明这个后端隔离不了什么。不要把它接到真实模型上。

`ci/ai-review.yml` 只是给读者拷贝的示例，没有放进本仓库的 `.github/workflows/`：它要自托管的 Linux runner 和模型服务，而公开仓库挂自托管 runner 有被不可信 PR 攻陷的风险，所以本仓库不运行它。

## 跑 CI 演示

只在 Linux 上测过。需要 [act](https://github.com/nektos/act)（修订时用的是 0.2.96）和 Node.js（act 在本机模式下用它跑 `actions/checkout`、`actions/upload-artifact`；首次运行会从 GitHub 克隆这两个 action）。

```sh
bash ci/run_ci_demo.sh bwrap               # 或 docker；act 不在 PATH 上时用 ACT=/path/to/act
```

它造一个示例仓库和几个 PR 分支，按 `pull_request` 事件逐个运行 workflow，覆盖：带 bug 的 PR 失败、干净 PR 通过、配置错误标成 exit 2、改了审查脚本的 PR 仍被拦下、fork PR 被跳过、artifact 里有报告和补丁。act 与真实 GitHub 的差别见博客正文；这里的结果不等于在 GitHub 上验证过。

把 workflow 用到自己的仓库：复制到 `.github/workflows/ai-review.yml`，把 `review.py` 放到 `tools/review.py`，在仓库变量里设 `LLM_BASE_URL`、`AI_REVIEW_MODEL`，可选 `AI_REVIEW_SANDBOX`（默认 docker）；模型服务有鉴权时再加 secret `LLM_API_KEY`。公开仓库不要用自托管 runner 跑 PR。

## 接真实模型

在仓库根目录或任意子目录下运行：

```sh
export LLM_BASE_URL="http://localhost:11434/v1"   # Ollama；默认值就是这个。也可以指向 LiteLLM 等 OpenAI 兼容网关
python3 /path/to/review.py --model <模型名> --sandbox bwrap --context tests/test_orders.py --lang 中文   # macOS 用 --sandbox docker
```

复测真实模型：`bash realmodel/run_real.sh <模型名> <后端> 3`，结果写到 `realmodel/results/`（可用 `OUT=目录` 改），再用 `python3 realmodel/analyze.py <目录>/run-*.json` 看每次真正执行了几条代码。

模型必须支持函数调用：`ollama show <模型名>` 的 Capabilities 里要有 `tools`（旧版 Ollama 不显示这一栏），而且发一条带工具的最小请求时，返回里要真的有 `tool_calls`（博客正文有示例命令）。能发 `tool_calls` 也不等于能做完审查：Mac 上的 `qwen2.5-coder:7b` 通过了这条测试，但三次审查都没交出一份合格的 `submit_review`（见 `realmodel/results-macos/`）。

常用参数：
- `--allow-domain HOST`（可重复，只限 docker/podman）：经白名单代理放行指定域名，端口只能是 80/443，不放行本地或私有地址；默认断网。
- `--shell-timeout`（默认 120 秒，最多 300）、`--max-output`（默认 16384 字符，最多 65536）。
- `--image`：docker/podman 用的镜像，可以换成预装依赖的镜像。

退出码：0 表示通过；1 表示有阻断级发现（默认只算 `confirmed=true` 且 severity 为 high 的发现）；2 表示没有完成，包括环境、git、沙箱、网络等各类错误，以及收到 SIGTERM（退出前仍会删掉容器和临时目录）。

已知限制：
- 补丁不进沙箱，模型只能针对原始代码做检查；修复是否有效，要在 `--apply` 之后用你自己的测试验证。
- 模型在沙箱里用 `run_shell` 改动或删除的文件不会进入补丁；补丁只记录 `edit_file`、`create_file`、`delete_file`。
- bwrap 后端不支持按域名放行网络；macOS 的 Docker Desktop 上 `--allow-domain` 也不可用。
- 小模型自报的 `confirmed` 不可信：qwen3 4B 三次运行都没有真正执行检查脚本，但每条发现都标了 `confirmed=true`（见 `realmodel/results/`）；qwen2.5-coder 7B 被打回的提交里还附了编造的"运行输出"（见 `realmodel/results-macos/`）。请以报告里的工具输出为准。
- 使用 `--head` 时，`--context` 指定的文件从工作区读取。
