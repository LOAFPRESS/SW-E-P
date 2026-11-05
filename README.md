# SW-E-P（Software Engineering Project）

> 软件工程项目 · 小组编号：8
> 项目网站：https://github.com/LOAFPRESS/SW-E-P

## 项目简介

复现一篇 TSE 2026 论文《Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions》中的 LLM 辅助实证分析框架：重建两阶段 LLM 标注流水线（评论分类 + 采纳判断），并用随机森林（Random Forest）+ SHAP 做可解释性分析。复用公开的 Zenodo 数据集与原始 prompt，无需重新采集数据。

## 团队成员

| 姓名 | 角色 | 模块 | 强项 |
|------|------|------|------|
| 尹捷睿 | 组长 | 数据与评估 | Python 数据处理、清洗、指标计算、单元测试、集成与进度协调 |
| 刘思懿 | 成员 | LLM 标注流水线 | LLM API 集成、prompt 工程、批量推理脚本、调试 |
| 杨弋驰 | 成员 | ML 可解释性 | 机器学习建模、SHAP 分析、数据可视化、报告撰写 |

## 功能特性

- 加载并校验评论数据集（评论文本、代码 diff/hunk、触发方式、工具类型、标签）
- 自动将评论分类为 None / General / Valid（Stage-1）
- 为 Valid 评论提取可执行的问题清单
- 判断采纳状态（Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed，Stage-2）
- 按预定义 schema 导出标注结果 CSV
- 训练随机森林模型并输出 Overall Accuracy 与 Macro-F1
- 生成 SHAP 特征重要性及方向性可视化
- 通过 `python run.py` 一条命令端到端运行全流程

## 目录结构

```
SW-E-P/
├── README.md                      # 项目介绍（本文件）
├── proposal.md                    # 项目提案（Task1，Markdown 版）
├── Task1-Project Proposal-Final.docx  # 项目提案（Word 版，含格式模板）
├── run.py                         # 唯一入口（annotate / validate-data）
├── requirements.txt               # 运行依赖（标注流水线 + RQ3 建模）
├── config/
│   ├── config.yaml                # 默认配置（mock provider，离线可跑）
│   ├── config.gold150.yaml        # 真实 150 条 gold 的 mock 冒烟
│   ├── config.deepseek.yaml       # 真实标注：deepseek-flash（Stage-1 不思考 / Stage-2 思考）
│   ├── config.qwen.yaml           # 真实标注：qwen-plus + qwen-max
│   └── config.openai.yaml         # OpenAI 对照实验（limit: 5）
├── prompts/
│   ├── stage1_v2_original.md      # 论文附录原版 Stage-1（当前主用，format: text）
│   ├── stage2_v2_original.md      # 论文附录原版 Stage-2
│   ├── stage1.md / stage2.md      # 早期重建版（JSON 契约，mock 演示用）
│   └── CHANGELOG.md               # prompt 版本与来源对照（DOM-1.2）
├── src/swep/                      # 两阶段标注流水线源码
│   ├── cli.py  config.py  pipeline.py  schema.py  metrics.py  export.py  providers.py
│   ├── features.py  rf.py  explain.py  rq3.py  # RQ3：特征矩阵 / 5 折 RF / SHAP / 编排
│   ├── data/loader.py             # 多格式读取 + column_map 列名适配
│   ├── data/zenodo.py             # Zenodo 附录 → 150 条 gold + provenance
│   ├── prompts/builder.py         # 模板渲染、上下文截断、版本指纹
│   └── llm/                       # mock / OpenAI 兼容客户端、解析、重试、缓存、计价
├── scripts/
│   ├── build_gold_dataset.py      # 从本机 Zenodo 目录重建 data/gold150.jsonl
│   └── run_rq3.py                 # RQ3 入口：分层 5 折 RF + SHAP（--ai-only 对照）
├── data/
│   ├── README.md                  # 数据来源、构建规则、字段契约、别名表
│   ├── gold150.jsonl              # 150 条真实 gold（+ .provenance.json）
│   └── samples/sample_comments.jsonl  # 12 条合成样例（synthetic: true）
├── tests/                         # 292 个 pytest 用例
├── docs/
│   ├── annotation-pipeline.md     # 标注模块设计说明（架构/配置/用法/产物）
│   ├── annotation-csv-schema.md   # annotations.csv 21 列数据契约
│   ├── rq3-rf-shap.md             # RQ3 复现协议、结果对照与交接说明
│   └── paper-deviations.md        # 与论文的偏差登记（DEV-01 ~ DEV-12）
└── artifacts/                     # 运行产物（gitignore，可重建）
```

## 标注模块（刘思懿）· W3–W4 里程碑

两阶段 LLM 标注流水线已可运行，三种方式任选：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# A) 离线演示（12 条合成样例，无需 key）
.\.venv\Scripts\python.exe run.py annotate -c config/config.yaml --write-report

# B) 真实 150 条 gold + mock（验证管线能吞下真实数据）
.\.venv\Scripts\python.exe scripts\build_gold_dataset.py
.\.venv\Scripts\python.exe run.py annotate -c config/config.gold150.yaml --no-cache --write-report

# C) 真实模型（DeepSeek，论文原版 prompt）
#    key 只留在你的终端环境里，不要贴进对话或写进仓库
setx DEEPSEEK_API_KEY "sk-..."     # 执行一次后重开终端；或当前会话 $env:DEEPSEEK_API_KEY = "sk-..."
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --limit 3 --dry-run   # 先看成本
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --limit 3 --no-cache  # 3 条试跑
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --write-report       # 150 条正式跑

.\.venv\Scripts\python.exe -m pytest tests -q                           # 292 passed
```

`config/config.deepseek.yaml` 用的是 DeepSeek 2026-11 的模型名：`deepseek-flash`
（Stage-1 关闭思考 `reasoning_effort: none`，Stage-2 打开思考 `high`）；想用更强的
`deepseek-v4-pro` 只改 `stage2_model` 并相应提高 `llm.budget.max_usd`。

Qwen 只需换 `-c config/config.qwen.yaml` 并设 `DASHSCOPE_API_KEY`；OpenAI 对照用 `config/config.openai.yaml`。
稳定性实验：加 `--repeat 5`（自动禁用缓存，输出运行间一致率与逐次分布）。

产物在 `artifacts/`：`annotations.csv`（21 列固定 schema）、`summary.json`（含分来源指标
`evaluation.per_source`、`--repeat>1` 时的 `stability`）、`run_report.md`、
`requests.jsonl`（逐次调用的 token/费用审计）、`run.log`、`cache.sqlite3`（断点续跑）。

- 模块设计、配置项、CLI 与退出码：[docs/annotation-pipeline.md](docs/annotation-pipeline.md)
- CSV 列字典与标签定义（给组长/杨弋驰的接口）：[docs/annotation-csv-schema.md](docs/annotation-csv-schema.md)
- 与论文的偏差（模型替代、`describe_code_change` 重建、gold 口径待核等）：[docs/paper-deviations.md](docs/paper-deviations.md)
- 数据来源与列名映射：[data/README.md](data/README.md)

**下一步**：设 `DEEPSEEK_API_KEY` 跑 150 条 → 用 `evaluation.per_source` 对照论文 Table VII
（Stage-1 OA 94.5%/F1 90.8%、Stage-2 OA 91.8%/F1 88.5%；file 83.6/78.1、hunk 89.2/83.4、human 85.6/62.4）
→ 用 `--repeat 5` 补运行间一致性 → 与组长对齐 DEV-10 的 RQ3 标签口径。

## RQ3 模块（特征 + 随机森林 + SHAP）· W5–W6

用附录给的同一份特征矩阵（3879 条 LLM 判 Valid 的评论 × 33 列）与标签，复现论文的
分层 5 折随机森林与 SHAP 解释，**不需要重建特征、不需要 API key**：

```powershell
# 主实验：3879 条，保留 Human（36 个特征）
.\.venv\Scripts\python.exe scripts\run_rq3.py --output artifacts\rq3\all_reviews

# 对照实验：去掉 Human 的 2990 条（33 个特征）
.\.venv\Scripts\python.exe scripts\run_rq3.py --ai-only --output artifacts\rq3\ai_only
```

复现结果与论文对照：

| 变体 | 样本 | 本项目 Accuracy / Macro-F1 | 论文 | 差 |
| --- | --- | --- | --- | --- |
| 主实验 | 3879 | **0.8876 / 0.8484** | 0.886 / 0.846 | +0.16 pp / +0.0024 |
| AI-only | 2990 | **0.9187 / 0.6553** | 0.917 / 0.647 | +0.17 pp / +0.008 |

产物：`rq3_metrics.json`、`rq3_feature_importance.csv`（含 rank）、`rq3_group_importance.csv`、
`rq3_shap_summary.png`、`rq3_shap_bar.png`、`rq3_report.md`（五折表 + SHAP Top-15 + 缺失列清单）。

- 协议逐条对齐、SHAP 结果表、交接给杨弋驰的说明：[docs/rq3-rf-shap.md](docs/rq3-rf-shap.md)
- 特征可用性（缺 10 列）与"未用我们重跑标签"两条偏差：DEV-11 / DEV-12（见 docs/paper-deviations.md）

