# RQ3 · 随机森林 + SHAP 复现说明（W5–W6）

> 本模块对应计划书 §3.7.3（杨弋驰：随机森林与可解释性分析）与 TABLE 3 的 W5–W6。
> 当前实现由刘思懿按"数据与协议先行"的方式完成第一版，供杨弋驰接手做解释与撰写；
> 需求依据：REQ-1.1 ~ REQ-1.8（可配置、无硬编码、数据不一致要报错）、DOM-1.2（记录偏差）。

## 1. 这一步回答什么

论文 RQ3 问的是：**哪些特征与"评论被采纳"相关？** 做法是用随机森林在 3879 条
"LLM 判定为 Valid" 的评论上做二分类（Addressed / Not Addressed），再用 SHAP 解释模型。
它和 RQ2（LLM 标注准不准）是两条独立的线：

| | RQ2（标注准确性） | RQ3（采纳因素） |
| --- | --- | --- |
| 数据 | 150 条人工 gold（分层抽样） | 3879 条 LLM 判 Valid 的评论 |
| 任务 | 六分类 / 二分类准确率 | 二分类 + 特征重要性 |
| 负责 | 刘思懿（本模块已交付） | 杨弋驰（本轮完成第一版） |

## 2. 数据从哪来

附录已经把论文用的两份输入直接给出，**不需要我们重建特征**：

| 文件 | 位置（相对 Zenodo 根） | 规模 |
| --- | --- | --- |
| 特征矩阵 | `address_feature_matrix/_selected_reviews_with_features/reviews_contains_valid_by_LLM_lda_topics_selected.csv` | 3879 行 × 33 列 |
| 标签 | `address_feature_matrix/labels/all_reviews_with_LLM_labels.csv` | 3879 行 × 2 列（`Comment_ID`、`Change_Label`） |

- 标签口径：`shape_labels_and_feature_under_LLM.py` 只保留 `Resolution_Formated` 以 `2` 开头且
  ≠ `2,-1` 的评论，并做 `2,0 → 0`、`2,1 → 1`、`2,2 → 1`。
- 分布：`Change_Label=1` 973 条 / 3879 = **25.08%**，与论文 RQ3 的 25.1% 吻合（详见 DEV-10）。
- 按 `Source == Human` 拆：human 889 条（Addressed 78.6%）、AI-only 2990 条（Addressed 9.16%），
  与论文的 2990 条 / 9.2% 完全对应——**AI-only 这一组是"去掉人类评论后模型还能不能判"的对照实验**。

## 3. 复现协议（逐条对齐附录 `analyze_feature_importance_with_rf.py`）

| 环节 | 附录做法 | 本项目实现 |
| --- | --- | --- |
| 交叉验证 | `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)` | 同（`src/swep/rf.py`） |
| 分类器 | `RandomForestClassifier(random_state=42)`，其余默认 | 同（不调参、不加 class_weight） |
| 特征 | 36 个（repo 3 / modification 12 / textual 5 / action 10 / topic 6） | 同（`src/swep/features.py`） |
| 文本向量 | 有 TF-IDF 分支，但主实验 `tfidf: False` | 未实现 TF-IDF，与主实验一致 |
| source 变量 | 论文另跑一版"AI-only"，去掉 Human 并二值化 Trigger/Model | `--ai-only`（`Is_Human` 剔除，33 特征） |
| 解释器 | `shap.TreeExplainer(model, data=train, feature_perturbation="interventional")` | 同，逐折训练后用测试集解释 |
| 正类 | 二分类取 `shap_values[1]` | 同（`_positive_class`） |
| 聚合 | 5 折 SHAP 拼接后出 summary plot | 同，另加 CSV 与 group 汇总 |

`interventional` 模式配 `data=` 背景集，是慢但可复现的 SHAP 口径；这也意味着
**SHAP 依赖随机种子与折划分**，换种子数值会变，排序大致稳定。

## 4. 怎么跑

```powershell
# 主实验（3879 条，保留 Human）
.\.venv\Scripts\python.exe scripts\run_rq3.py --output artifacts\rq3\all_reviews

# AI-only 对照（2990 条）
.\.venv\Scripts\python.exe scripts\run_rq3.py --ai-only --output artifacts\rq3\ai_only

# 只算指标不出 SHAP（快，约 5 秒）
.\.venv\Scripts\python.exe scripts\run_rq3.py --no-shap
```

产物（每个 `--output` 目录一份）：`rq3_metrics.json`、`rq3_feature_importance.csv`、
`rq3_group_importance.csv`、`rq3_shap_summary.png`、`rq3_shap_bar.png`、`rq3_report.md`。

常用参数：`--zenodo-root`（Zenodo 包路径）、`--groups`（只用部分特征组）、`--n-splits`、
`--random-state`、`--n-estimators`、`--action-binary/--no-action-binary`、`--no-plot`。

## 5. 结果

### 5.1 主实验（3879 条，36 特征）

| 指标 | 本项目 | 论文 | 差 |
| --- | --- | --- | --- |
| Accuracy | **0.8876** ± 0.0110 | 0.886 | +0.16 pp |
| Macro-F1 | **0.8484** ± 0.0136 | 0.846 | +0.0024 |

逐折（accuracy / macro-F1）：0.9059/0.8697、0.8840/0.8437、0.8737/0.8316、0.8814/0.8391、0.8929/0.8576。

SHAP Top-10（mean |SHAP|，正类）：

| 排名 | 特征 | mean abs SHAP | 方向（mean SHAP） |
| --- | --- | --- | --- |
| 1 | Is_Human | 0.0422 | +0.0104 |
| 2 | Trigger_auto | 0.0400 | +0.0088 |
| 3 | Is_File_Level_Action | 0.0323 | +0.0014 |
| 4 | Author_Past_Commit_Count | 0.0251 | +0.0015 |
| 5 | Repo_Total_File_Size | 0.0192 | +0.0014 |
| 6 | Code_Text_Ratio | 0.0154 | +0.0030 |
| 7 | Text_Length | 0.0126 | +0.0029 |
| 8 | LDA_Topic_Prob_2 | 0.0117 | +0.0019 |
| 9 | LDA_Topic_Prob_1 | 0.0108 | +0.0007 |
| 10 | Repo_Total_Issue_Number | 0.0105 | +0.0021 |

特征组（sum |SHAP|）：source 0.1531（10 个）> textual 0.0963（11）> modification 0.0809（12）
> repo 0.0359（3）。**"是不是人类评论""是不是自动触发"主导了模型**，这与论文的定性叙述一致：
> 人类评论更容易被采纳。

### 5.2 AI-only 对照（2990 条，33 特征）

| 指标 | 本项目 | 论文 | 差 |
| --- | --- | --- | --- |
| Accuracy | **0.9187** ± 0.0062 | 0.917 | +0.17 pp |
| Macro-F1 | **0.6553** ± 0.0335 | 0.647 | +0.008 |

逐折（accuracy / macro-F1）：0.9181/0.6599、0.9264/0.6909、0.9147/0.6373、0.9097/0.6010、0.9247/0.6877。

SHAP Top-10：

| 排名 | 特征 | mean abs SHAP |
| --- | --- | --- |
| 1 | Author_Past_Commit_Count | 0.0215 |
| 2 | Source_coderabbitai/ai-pr-reviewer | 0.0186 |
| 3 | Code_Text_Ratio | 0.0125 |
| 4 | Commit_Accumulated_Total_Del_Line_Count | 0.0115 |
| 5 | Commit_Base_Total_Line_Count | 0.0111 |
| 6 | Repo_Total_File_Size | 0.0098 |
| 7 | Comment_Adds | 0.0098 |
| 8 | Is_File_Level_Action | 0.0092 |
| 9 | LDA_Topic_Prob_5 | 0.0088 |
| 10 | LDA_Topic_Prob_1 | 0.0078 |

与论文 Top-10 的重叠（8/10）：Author Prior Commits、Code Text Ratio、Commit Base Lines、
Commit Del、Repo File Size、Comment Adds、Is File Level Action、LDA Topic 5。

特征组：modification 0.0797 > textual 0.0717 > source 0.0402 > repo 0.0202。
去掉人类评论后，**"改动规模 + 仓库/文件上下文"顶上来了**，这正是论文"简洁评论、带代码片段、
手动触发、hunk 级更易被采纳"四条结论的模型侧证据。

## 6. 与论文的差异（对应 `docs/paper-deviations.md`）

- **DEV-11**：附录的特征表只有 33 列，论文特征清单里的 10 个列在本表里**不存在**
  （`Code_Total_Length`、`Comment_Changes`、`Commit_Accumulated_Changed_File_Count`、
  `Commit_Accumulated_Total_Add_Line_Count`、`Commit_Accumulated_Total_Change_Line_Count`、
  `File_Change_Line_Count`、`Repo_Total_File_Number`、`Repo_Total_PR_Number`、
  `Thread_Companion_Count`、`Timeline_Index`）。我们的做法是**不做任何替代**：
  `build_feature_matrix` 把这些列记进 `missing["numeric"]`，`rq3_report.md` 末尾原样列出，
  特征数因此是 36 而不是论文清单的 46；准确率仍落在论文 ±0.2 pp 内，说明这 10 列贡献很小，
  但**不能声称逐特征完全一致**（详见 `docs/paper-deviations.md` 的 DEV-11）。

- **来源变量命名**：论文图里写作 "Is Action 3"，我们按 `Source_<action>` one-hot 实现，语义相同、字面不同。
- **RF 超参**：附录未调参，我们也用默认值；论文也没有报告调参搜索结果，因此可比。
- **SHAP 数值**：`interventional` + 5 折拼接，绝对值依赖种子；只用于**排序与方向**的定性比较。

## 7. 交接给杨弋驰

可以直接用：

1. `artifacts/rq3/all_reviews/rq3_report.md` 与 `ai_only/rq3_report.md`：五折表 + SHAP Top-15 + group 表。
2. `rq3_feature_importance.csv`：完整 36（33）行、含 rank，画自己的柱状图很方便。
3. `rq3_shap_summary.png` / `rq3_shap_bar.png`：可直接进 PPT（dpi 150）。
4. 若要重跑：`scripts/run_rq3.py`，参数见 §4；数据路径默认指向本机 Zenodo 包。

注意三点：

- SHAP 解释的是**这个模型**的行为，不是因果；写报告时用"与……相关"而不是"导致"。
- AI-only 的 Macro-F1 只有 0.65，因为正类只占 9.2%——**不要只报 accuracy**，会被问"是不是全判 0"。
  我们的 `rq3_report.md` 已把 macro-F1 与逐折结果并列，写论文时请一并保留。
- 如果之后要换成"用我们重跑的 3879 条标签"，只需替换 `--labels` 指向我们产出的 CSV，
  特征矩阵与折划分都不用动，这样就能把"prompt 移植是否正确"量化成两次标签的一致性。

## 8. 下一步

- [ ] 用我们重跑的 3879 条 LLM 标签（需要 API key）与附录标签做一致性对比，作为 RQ3 的敏感性分析。
- [ ] 杨弋驰：基于本文档撰写 RQ3 小节 + 图注，把四条结论与 SHAP 排名对应起来。
- [ ] W7 集成时把本模块接入 `run.py rq3` 子命令（当前是独立脚本，避免与标注流水线耦合）。
