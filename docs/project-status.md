# 项目进度与交接（2026-11-09 核对）

> 用途：把计划书的 8 周任务、仓库里实际存在的东西、还没人认领的空白放在一张表里，
> 让组里其他成员（或下一次接手的自己）能直接看出"现在在哪、下一步做什么"。
> 核对方式：`git fetch --all --prune` + `git branch -a` + 本地 `P1/` 目录时间戳。

## 1. 仓库现状（截至本条提交）

- 远端：`origin https://github.com/LOAFPRESS/SW-E-P.git`，只有一个分支 `main`。
- 提交历史里**只有刘思懿的提交**（`3ead5c3` 起 7 个），队友尚未推送任何分支或代码。
- 因此"补位"只能落在**接口与空白文档**上，不能替别人写他们该负责的分析结论。

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
| 本条提交 | prompt v2.1 A/B、`run.py rq3` 单一入口、四条结论核对、本状态表 |

## 2. 计划书任务 vs 实际状态

| 周次 | 计划任务 | 负责 | 状态 |
| --- | --- | --- | --- |
| W1–W2 | 精读、Zenodo 数据核对、搭环境 | A（B/C 配合） | ✅ Zenodo 包已落地并核验（`data/README.md`、DEV-07 关闭）；`.venv` 已建 |
| W3–W4 | 两阶段 LLM 标注流水线 + gold 子集批量推理 | **B（刘思懿）** | ✅ 完成，含 150 条真实跑批 + prompt v2.1 A/B（`docs/rq2-results.md`） |
| W5–W6 | 特征子集 + 分层 5 折 RF + SHAP | C（杨弋驰） | ✅ 代码与结果在 `docs/rq3-rf-shap.md`（由 B 补位实现，C 可直接接手写正文） |
| W7–W8 | 集成、端到端、复现原结论、偏差与有效性威胁 | A（尹捷睿）牵头 | 🟡 本文件 + `docs/rq3-conclusions.md` + `run.py rq3` 是补位部分；报告正文仍待 A |

## 3. 这一轮补了什么（给队友的接口）

1. **单一入口补齐**：`run.py` 现在有 `validate-data` / `annotate` / `rq3` 三个子命令，
   满足 URS REQ-1.13（Should，单入口）。之前 `rq3` 只能通过 `scripts/run_rq3.py` 跑。
   `scripts/run_rq3.py` 保留为薄封装（同样的参数，便于习惯脚本的人）。
2. **"复现原结论"的数据**：`docs/rq3-conclusions.md` + `scripts/rq3_conclusions.py`，
   把论文四条实践结论在 3879 条建模集上逐条算了采纳率，并给出 Human 混淆的解释。
   这直接就是 W7–W8 报告里"RQ3 结论"一节可以引用的素材。
3. **状态表**：本文件。计划书里的"谁在第几周做什么"与仓库现状对齐，避免重复劳动。

## 4. 还空着的（建议认领）

| 事项 | 为什么还没做 | 建议 |
| --- | --- | --- |
| RQ2 `--repeat 5` 稳定性实验 | 需真实 key，成本约 $1.2 / 75 min（DEV-04） | 有 key 时由 B 跑，结果并入 `docs/rq2-results.md` |
| v2.1 的 held-out 复核 | 四条规则是样本内调的（DEV-13） | 按来源分层留 30 条不参与调参，只测一次；$0.06 / 4 min |
| 报告正文（RQ1/RQ2/RQ3 三节 + 有效性威胁） | 属 A 的 W7–W8 | A 可直接引用 `docs/` 下六份分析文档，不必重跑 |
| 演示用 PPT / 最终打包 | 计划书未排周次 | 沿用 H1 的做法（脚本生成 docx/pptx + `final/` 打包） |
| Zenodo 以外的外部效度讨论 | 需 A 的领域判断 | 建议单列一节：3 个 action 家族、2 种语言、单一时间窗 |

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
```

## 6. 交接时的三个提醒

1. **150 条 gold 不是 RQ3 的分母**：RQ3/结论分析用 3879 条建模集（DEV-10 已查明），两者别混。
2. **DeepSeek 的两个模型名与思考模式**：`deepseek-flash` / `deepseek-v4-pro`；
   `deepseek-chat` / `deepseek-reasoner` 已下线。思考模式下 `temperature` 无效（DEV-09）。
3. **一切偏差都登记在 `docs/paper-deviations.md`（DEV-01…DEV-13）**：写报告时逐条对照，
   不要凭印象说"和论文一致"。
