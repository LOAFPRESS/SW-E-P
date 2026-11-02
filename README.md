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
├── requirements.txt               # 标注模块运行依赖
├── config/
│   ├── config.yaml                # 默认配置（mock provider，离线可跑）
│   └── config.openai.yaml         # 真实调用示例（limit: 5）
├── prompts/
│   ├── stage1.md                  # Stage-1 有效性判定 prompt
│   ├── stage2.md                  # Stage-2 采纳判定 prompt
│   └── CHANGELOG.md               # prompt 版本与重建说明（DOM-1.2）
├── src/swep/                      # 两阶段标注流水线源码
│   ├── cli.py  config.py  pipeline.py  schema.py  metrics.py  export.py
│   ├── data/loader.py             # 多格式读取 + column_map 列名适配
│   ├── prompts/builder.py         # 模板渲染、上下文截断、版本指纹
│   └── llm/                       # mock / openai 客户端、解析、重试、缓存、计价
├── data/
│   ├── README.md                  # 数据契约、别名表、column_map 指南
│   └── samples/sample_comments.jsonl  # 12 条合成样例（synthetic: true）
├── tests/                         # 154 个 pytest 用例
├── docs/
│   ├── annotation-pipeline.md     # 模块设计说明（架构/配置/用法/产物）
│   ├── annotation-csv-schema.md   # annotations.csv 21 列数据契约
│   └── paper-deviations.md        # 与论文的偏差登记（DEV-01 ~ DEV-08）
└── artifacts/                     # 运行产物（gitignore，可重建）
```

## 标注模块（刘思懿）· W3–W4 里程碑

两阶段 LLM 标注流水线已可运行，**默认 mock provider，无需 API key、无需数据集即可端到端跑通**：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py validate-data -c config/config.yaml   # 只校验数据
.\.venv\Scripts\python.exe run.py annotate -c config/config.yaml --write-report
.\.venv\Scripts\python.exe -m pytest tests -q                           # 154 passed
```

真实调用：设置 `OPENAI_API_KEY` 后 `python run.py annotate -c config/config.openai.yaml`。

产物在 `artifacts/`：`annotations.csv`（21 列固定 schema）、`summary.json`、`run_report.md`、
`requests.jsonl`（逐次调用的 token/费用审计）、`run.log`、`cache.sqlite3`（断点续跑）。

- 模块设计、配置项、CLI 与退出码：[docs/annotation-pipeline.md](docs/annotation-pipeline.md)
- CSV 列字典与标签定义（给组长/杨弋驰的接口）：[docs/annotation-csv-schema.md](docs/annotation-csv-schema.md)
- 与论文的偏差（prompt 重建、合成样例、5 次重复等）：[docs/paper-deviations.md](docs/paper-deviations.md)
- 数据契约与列名映射：[data/README.md](data/README.md)

**下一步**：拿到 Zenodo 数据与原始 prompt 后，用 `data.column_map` 对接真实 CSV，
小批量真实调用对齐论文 Table VII（Stage-1 OA 94.5%/F1 90.8%、Stage-2 OA 91.8%/F1 88.5%），
并补充分来源指标（DEV-06）与 5 次重复实验（DEV-04）。
