# 有效性威胁（Threats to Validity）

这一份不是论文的翻译，而是**我们这个复现项目自己的**威胁清单：每条威胁写清
①它是什么、②我们手上的证据、③我们做了什么、④报告里应该怎么写。
按论文的惯例分四类，编号 T-*，方便在报告里引用。

数字来源：`docs/rq2-results.md`、`docs/rq3-rf-shap.md`、`docs/rq3-label-sensitivity.md`、
`docs/paper-deviations.md`（DEV-01…DEV-13）、`artifacts/reproduction/report.md`。

## 1. 结论效度（Conclusion Validity）

| 编号 | 威胁 | 证据 | 处理 | 报告里怎么写 |
| --- | --- | --- | --- | --- |
| T-01 | LLM 输出不确定，单次运行的数字带运气成分 | 论文每个模型跑 5 次；我们只跑 1 次（DEV-04） | `run.py annotate --repeat N` 已实现，`--no-cache` 强制真调；未跑 5 次是预算原因（约 $1.2 / 75 min） | 引用数字时写"单次运行"；把 5 次一致性列为未完成项 |
| T-02 | 150 条的样本量小，分来源后每类只有 50 条 | 分来源六分类 accuracy：file 0.740 / hunk 0.800 / human 0.900（v2.1） | 报告里同时给 accuracy 与 macro-F1，并给逐折波动（RQ3 全量 accuracy ±0.0110、AI-only ±0.0062；六分类 macro-F1 ±0.0136） | 不给单点结论，写"落差集中在 file-level，n=50" |
| T-03 | 类别不均衡：Valid-Unaddressed 43 条、Valid-Uncertain 6 条 | 六类分布见 `docs/rq2-results.md` | 用 macro-F1 而不是 accuracy 作主指标；二分类口径单列 | 六类准确率高但 F1 低，必须两个数一起给 |

## 2. 内部效度（Internal Validity）

| 编号 | 威胁 | 证据 | 处理 | 报告里怎么写 |
| --- | --- | --- | --- | --- |
| T-04 | **模型替换**：论文 GPT-4.1 + o3-mini，我们 DeepSeek flash（DEV-09） | 六分类 81.3 / 80.1 vs 86.1 / 74.6（−4.8pp / +5.5pp）；二分类 91.3 / 91.3 vs 91.5 / 89.8（−0.2pp） | 用论文附录原版 prompt、原版两阶段结构；模型在论文自己的 `registry.py` 里登记过 | 把差距写成"模型能力差异"，不写成"复现失败"；重点引二分类几乎重合 |
| T-05 | **prompt v2.1 是样本内调参**（DEV-13） | 四条规则是看过这 150 条的 19 个 stage-1 错误之后写的 | 只写规则不写示例；只改 Stage-1；A/B 只隔离 Stage-1；报告里标 DEV-13 | v2.1 的提升（87.3→91.3）**不能**算干净改进；写"样本内改进，需 held-out 复核" |
| T-06 | RQ3 用论文现成标签，不是我们重标的（DEV-12） | 重叠 110 条上两套标签一致率 92.7 %、κ 0.835；换标签 RF 0.7909 / 0.7364（论文标签 0.7273 / 0.6716，n=110）；SHAP 名次平均移动 3.78 | 写了 `scripts/rq3_label_sensitivity.py`，结果并入 `docs/rq3-label-sensitivity.md` 与复现包 | 写"标签体系可移植有正面证据；全量 3,879 条未重标" |
| T-07 | 特征表缺 10 列（DEV-11） | 附录特征表 33 列，论文说初始 45 → 去相关后 36；我们构建出 36 列但成分不同 | 不替用户补造特征，缺列在 `rq3_report.md` 里逐条列出 | 明确"36 个特征不是同一组 36 个"；RQ3 指标吻合（88.8 vs 88.6）说明差异影响有限 |
| T-08 | 解析与标签归一化引入了我们的判断 | `parse_stage1_text` 的"Classification 取最早出现"、Valid 无 issue 时提升或降级、失败行写 error 列 | 规则写进 `docs/annotation-pipeline.md` §3.2，有 20 个单元测试覆盖 | 写"文本解析规则见附录/文档"；不把解析失败算作模型错误 |
| T-09 | 价格表是手抄快照（DEV-05） | gpt-4.1 2/8、o3-mini 1.1/4.4、deepseek-flash 0.30/1.20 等 | 价格只用于预算守卫，不影响标签 | 成本数字写"按 2025 年公开价目表估算" |

## 3. 构念效度（Construct Validity）

| 编号 | 威胁 | 证据 | 处理 | 报告里怎么写 |
| --- | --- | --- | --- | --- |
| T-10 | "addressed" 是二值合并（Partially + Fully），掩盖部分采纳 | 150 条里 Valid-Partially 13、Valid-Fully 58；RQ3 二分类 Addressed 25.1 % | 报告同时给六类与二分类两套口径（Table VII 四视角） | 二分类用于 RQ3，六类用于 RQ2；不要混着比 |
| T-11 | Stage-1 的"具体 / 泛化"边界本身主观 | 论文 κ：file 0.674、hunk 0.734、human 0.764（file-level 最低）；我们 19 个错误里 9 个在 General 边界 | 用论文原版标注指南（`statistics/RQ2/human annonation/Annotation Guidelines2.0.md`）作为口径 | 引用 κ 说明"人类标注本身也不一致"，我们 87–91 % 已接近上限 |
| T-12 | "采纳"用代码改动作代理，改动 ≠ 因为这条评论 | 论文只对 PR-level 抽查 30 条（1 条部分采纳），我们自己未做时间先后核验 | 沿用论文口径，并在局限里点名 | 写"相关性证据，不是因果" |
| T-13 | LLM 当裁判（LLM-as-judge）的偏好未知 | 我们没有任何人工复核样本 | 用 150 条人工 gold 作锚点；不做"模型自评" | 说明所有标签来自与 gold 的对照，而非模型互评 |

## 4. 外部效度（External Validity）

| 编号 | 威胁 | 证据 | 处理 | 报告里怎么写 |
| --- | --- | --- | --- | --- |
| T-14 | 覆盖面窄：16 个 action，但 4 个占 98.9 % 评论 | `docs/paper-deviations.md` 与 `data/README.md` 的 action 分布 | 报告里按 action 家族给采纳率（0.9 %–19.2 %） | 结论限定在"这四个主流 action"，不外推到全部 22,000+ 评论 |
| T-15 | 只保留英文评论 | 论文用 FastText 过滤，删掉约 75 % 评论与 47 个仓库（32 个纯韩语） | 我们无法恢复被删部分 | 明写"语料是英文子集" |
| T-16 | 单一时间窗（2025-01 至 2025-07 抽样） | 附录 README 与论文 §III | 引用论文 2025-07-23 的 Marketplace 复查 | 不声称代表 2026 年的工具行为 |
| T-17 | 只用 GitHub Actions 上的工具 | 研究对象即 Actions 机器人 | 无 | 结论限定在 GitHub Actions 场景 |
| T-18 | 我们的 gold 就是论文的 150 条，没有重新抽样 | `data/gold150.jsonl` 由附录 CSV 内连接得到（`scripts/build_gold_dataset.py`） | 好处是可对齐；代价是样本偏差被继承 | 明写"沿用论文抽样，未独立重采样" |
| T-19 | closed PR 的采纳率更低（ID-1 3.0 %，其余 0 %） | 论文 Discussion | 我们只统计 merged PR | 结论限定在 merged PR |

## 5. 一句话总结（可直接进报告结论）

> 本复现沿用论文的语料与 150 条 gold，用附录原版 prompt 与两阶段结构，
> 以 DeepSeek 替代原模型（六分类 −4.8pp、二分类 −0.2pp），
> 在标签体系上与原论文一致率 92.7 %（κ 0.835），RQ3 指标与 SHAP 排序在容差内重现；
> 主要局限是单次运行、样本量 150、以及全量 3,879 条未重标。

## 6. 还没做的（写报告时不要声称）

- 5 次重复的一致性（T-01）
- v2.1 的 held-out 复核（T-05）
- 3,879 条全量重标注（T-06）
- 人工复核我们的标签（T-13）
- 非英文评论、非 Actions 工具、closed PR（T-15、T-17、T-19）
