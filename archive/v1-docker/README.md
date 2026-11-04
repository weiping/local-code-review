# 上一版的测试记录

这里是 `review.py` 上一版（452 行，沙箱后端是 docker、podman、bwrap、unsafe-local）的测试输出和真实模型报告，保留作对照。
现行版本改用 Anthropic sandbox-runtime（srt），不再有 `--sandbox`、`--image` 这些参数，下面这些文件里的命令不能直接在现行版本上运行。
上一版的代码见本仓库 git 历史里的提交 `4e90f5f`。

| 目录或文件 | 内容 |
| --- | --- |
| `realmodel/results-macos-glm/` | Mac 上经 Magpie 接入 `auto/glm-5.3` 跑 3 次（docker 后端） |
| `realmodel/results/` | Linux 测试机上 `qwen3:4b-instruct-2507-q4_K_M` 跑 3 次（bwrap） |
| `realmodel/results-macos/` | Mac 上 `qwen2.5-coder:7b` 跑 3 次（docker） |
| `realmodel/results-macos-14b/` | Mac 上 `qwen2.5-coder:14b` 跑 3 次（docker，上下文 8192） |
| `realmodel/pilot/` | 用更早的提示词试跑的一次 |
| `demo-results-*.txt`、`ci-results-*.txt` | 上一版的假模型演示和 act CI 演示输出 |
