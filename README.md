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
├── docs/                          # 设计文档、UML 图
└── src/                           # 源代码
```
