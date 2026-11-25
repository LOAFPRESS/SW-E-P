# 项目进度与交接（2026-11-25 核对）

> 用途：把计划书的 8 周任务、仓库里实际存在的东西、还没人认领的空白放在一张表里，
> 让组里其他成员（或下一次接手的自己）能直接看出"现在在哪、下一步做什么"。
> 核对依据包括远端分支、GitHub Actions、本地 Git 历史和 `P1/` 中的作业材料。

## 1. 仓库现状（截至远端 `44b3425`）

- GitHub 远端目前只有 `main`，没有开放的 PR。
- 下表记录了标注、建模和集成的主要提交。小组分工与交接状态见下一节。

| 提交 | 内容 |
| --- | --- |
| `3ead5c3` | 两阶段标注流水线（W3–W4）：`src/swep`、prompts、21 列 CSV、154 测试 |
| `52607c4` | 分来源指标 + `--repeat` 稳定性（DEV-04 / DEV-06 工程侧消除） |
| `b666bfe` | 查明 DEV-10（RQ3 的 25.1% 分母是 3879 条建模集） |
| `e7df0e9` | 论文附录原版 prompt、真实 `data/gold150.jsonl`、DeepSeek/Qwen provider |
| `1839889` | 适配 2026-11 的 DeepSeek API（`deepseek-flash`、思考模式、阶段参数） |
| `af52cb7` | RQ3 复现（W5–W6）：`features/rf/explain/rq3`、`scripts/run_rq3.py`、295 测试 |
| `c6e89bb` | RQ2 首次真实跑批结果（`docs/rq2-results.md`） |
| `a73c461` | 修 openai 1.55.3 不认识 `reasoning_effort`（改走 `extra_body`） |
| `f8a6e4b` | prompt v2.1 A/B、`run.py rq3` 单一入口、四条结论核对、本状态表 |
| `24edf6c` | 测试数刷新到 295 |
| `edd3709` | 一键复现：`scripts/reproduce_all.py` 产出 `artifacts/reproduction/report.md` |
| `66521ed` | `run.py reproduce` / `--recompute` / `--rerun-llm`（单一入口收口） |
| `15188c2` | 标签灵敏度（DEV-12）：110 条重叠样本、κ 0.835、SHAP 名次移动 3.78 |
| `4d680a3` | 灵敏度并入复现包（`label-sensitivity.json` + report 一节） |
| `00909f2` | `docs/threats-to-validity.md`：19 条威胁与写法定稿 |
| `ae72dbc` | Data availability：引 Zenodo DOI、不提交原始 CSV |
| `2d69f8a` | 本状态表刷新（提交表、威胁清单状态、复现入口） |
| `7df57d9` | `tests/test_compare_runs.py`：A/B 脚本的四个视角与一致率有测试兜底（326 测试） |
| `95a1067` | GitHub Actions：push 触发 `pytest`（3.8 / 3.10 / 3.11 三个矩阵） |
| `c1c9d1a` | CI 修正：3.8 钉 `ubuntu-22.04`（24.04 的清单里没有 3.8） |

## 2. 计划书任务 vs 实际状态

| 周次 | 计划任务 | 负责 | 状态 |
| --- | --- | --- | --- |
| W1–W2 | 精读、Zenodo 数据核对、搭环境 | A（B/C 配合） | ✅ Zenodo 包已落地并核验（`data/README.md`、DEV-07 关闭）；`.venv` 已建 |
| W3–W4 | 两阶段 LLM 标注流水线 + gold 子集批量推理 | **B（刘思懿）** | ✅ 完成，含 150 条真实跑批 + prompt v2.1 A/B（`docs/rq2-results.md`） |
| W5–W6 | 特征子集 + 分层 5 折 RF + SHAP | C（杨弋驰） | ✅ 代码与结果在 `docs/rq3-rf-shap.md`（由 B 补位实现，C 可直接接手写正文） |
| W7–W8 | 集成、端到端、复现原结论、偏差与有效性威胁 | A（尹捷睿）牵头 | 🟡 端到端已闭环（`scripts/reproduce_all.py` 一条命令产出 `artifacts/reproduction/report.md`）；剩下的是报告正文与外部效度，仍待 A |

## 3. 这一轮补了什么（给队友的接口）

1. **单一入口补齐**：`run.py` 现在有 `validate-data` / `annotate` / `rq3` 三个子命令，
   满足 URS REQ-1.13（Should，单入口）。之前 `rq3` 只能通过 `scripts/run_rq3.py` 跑。
   `scripts/run_rq3.py` 保留为薄封装（同样的参数，便于习惯脚本的人）。
2. **"复现原结论"的数据**：`docs/rq3-conclusions.md` + `scripts/rq3_conclusions.py`，
   把论文四条实践结论在 3879 条建模集上逐条算了采纳率，并给出 Human 混淆的解释。
   这直接就是 W7–W8 报告里"RQ3 结论"一节可以引用的素材。
3. **端到端复现**：`scripts/reproduce_all.py` 把数据集自检、两次标注与论文的对照、
   prompt A/B、四条结论核对、RQ3 指标与 SHAP 收进一个出口，写 `artifacts/reproduction/report.md`
   与 `manifest.json`（含 Git commit、gold 数据和特征矩阵的 SHA-256）。入口为 `run.py reproduce`。
   `--recompute` 会重训 RF，`--rerun-llm` 会运行两套 DeepSeek 标注配置。用法见 `docs/reproduction.md`。
4. **标签灵敏度（DEV-12 的正面证据）**：`scripts/rq3_label_sensitivity.py` 在"我们标过、论文也标过"
   的 110 条上比较两套标签 —— 一致率 92.7%、κ 0.835；换标签重训 RF 为 0.7909 / 0.7364
   （论文标签 0.7273 / 0.6716，n=110，差距小于一个标准差）；SHAP 排序平均移动 3.78 位。
   见 `docs/rq3-label-sensitivity.md`。全量 3,879 条重标仍需要付费预算。
5. **状态表**：本文件。计划书里的"谁在第几周做什么"与仓库现状对齐，避免重复劳动。

## 4. 还空着的（建议认领）

| 事项 | 为什么还没做 | 建议 |
| --- | --- | --- |
| RQ2 `--repeat 5` 稳定性实验 | 需真实 key，成本约 $1.2 / 75 min（DEV-04） | 有 key 时由 B 跑，结果并入 `docs/rq2-results.md` |
| v2.1 的 held-out 复核 | 四条规则是样本内调的（DEV-13） | 按来源分层留 30 条不参与调参，只测一次；$0.06 / 4 min |
| 报告正文（RQ1/RQ2/RQ3 三节） | 属 A 的 W7–W8 | 可直接引用 `docs/` 下七份分析文档，不必重跑 |
| 有效性威胁一节 | 初稿已由 B 写出（`docs/threats-to-validity.md`，T-01…T-19） | A 只需按自己的判断删改，不要从零写 |
| 演示用 PPT / 最终打包 | 计划书未排周次 | 沿用 H1 的做法（脚本生成 docx/pptx + `final/` 打包） |
| Zenodo 以外的外部效度讨论 | 需 A 的领域判断 | T-14…T-19 已列出可用的事实（4 个 action 占 98.9%、英文子集、单一时间窗、merged PR） |
| CI 之外的质量门槛 | 只有 `pytest` 与入口冒烟 | 若要加，建议先加格式检查（`black --check`），别一次上太多 |

## 4b. 持续集成

`.github/workflows/tests.yml` 在推送到 `main` 或创建 PR 时运行离线测试。测试使用 mock provider 和测试构造的复现输入。
矩阵是 Python **3.8 / 3.10 / 3.11**。
3.8 钉在 `ubuntu-22.04`，因为 `ubuntu-24.04` 的 setup-python 清单里已经没有 3.8。
末尾还有一条入口冒烟（`run.py --help` + `validate-data`），因为仓库大多数功能都从 `run.py` 进。
2026-11-21 三个矩阵全绿。

2026-11-25 核对公开仓库，`main` 与本地的 `44b3425` 一致，最近一次 [Actions 运行](https://github.com/LOAFPRESS/SW-E-P/actions/runs/44897509425) 成功。
Git 忽略 `artifacts/`。新克隆需要先准备 Zenodo 附录和历史产物，或按[复现说明](reproduction.md)重新生成产物。
本地加入了缺失输入检查，328 个测试通过。用干净副本、Zenodo 数据和两份历史标注运行 `--recompute` 后，全量和 AI-only 的样本数、准确率与 Macro-F1 均与历史结果一致。

## 5. 复现入口（一条命令起）

```powershell
# 环境
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 自检（不需要 key）
.\.venv\Scripts\python.exe run.py validate-data -c config\config.gold150.yaml
.\.venv\Scripts\python.exe run.py annotate -c config\config.gold150.yaml --limit 3

# 真实标注（需要 DEEPSEEK_API_KEY）
.\.venv\Scripts\python.exe run.py annotate -c config\config.deepseek.yaml --write-report

# prompt A/B（v2.1 只改 Stage-1）
.\.venv\Scripts\python.exe run.py annotate -c config\config.deepseek-v21.yaml --write-report
.\.venv\Scripts\python.exe scripts\compare_runs.py artifacts\deepseek-paper\annotations.csv `
    artifacts\deepseek-v21\annotations.csv --labels v2 v2.1 --json artifacts\rq2-ab.json

# RQ3（不需要 key）
.\.venv\Scripts\python.exe run.py rq3
.\.venv\Scripts\python.exe run.py rq3 --ai-only
.\.venv\Scripts\python.exe scripts\rq3_conclusions.py

# 标签灵敏度（不需要 key，约 1 分钟）
.\.venv\Scripts\python.exe scripts\rq3_label_sensitivity.py --json artifacts\rq3-sensitivity\metrics.json

# 用已有标注和 RQ3 指标生成复现报告（不需要 key）
.\.venv\Scripts\python.exe run.py reproduce
```

## 6. 交接时的三个提醒

1. **150 条 gold 不是 RQ3 的分母**：RQ3/结论分析用 3879 条建模集（DEV-10 已查明），两者别混。
2. **DeepSeek 的两个模型名与思考模式**：`deepseek-flash` / `deepseek-v4-pro`；
   `deepseek-chat` / `deepseek-reasoner` 已下线。思考模式下 `temperature` 无效（DEV-09）。
3. **一切偏差都登记在 `docs/paper-deviations.md`（DEV-01…DEV-13）**：写报告时逐条对照，
   不要凭印象说"和论文一致"。

