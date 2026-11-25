# 一条命令复现全部数字

`scripts/reproduce_all.py` 把仓库里散在四个地方的数字收进同一个出口，避免写报告时
从五份文档里各抄一行、抄错一个小数点。

## 1. 运行方式

| 命令 | 做什么 | 花钱 | 用时 |
| --- | --- | --- | --- |
| `run.py reproduce` | 使用已有标注 CSV 和 RQ3 指标，重跑数据校验、标注对比、四条结论核对和标签灵敏度分析 | 0 | 随机器而异 |
| `run.py reproduce --recompute` | 使用已有标注 CSV，重新训练两套随机森林（全量 3,879 条、AI-only 2,990 条），计算 SHAP | 0 | 约 1–3 min |
| `run.py reproduce --rerun-llm` | 运行两套 DeepSeek 标注配置生成 CSV，使用已有 RQ3 指标 | 取决于缓存和 API 用量 | 无缓存约 40 min（历史实测） |

两个开关可独立使用，也可组合使用。`run.py reproduce` 将选项传给 `scripts/reproduce_all.py`。
`--rerun-llm` 需要 `DEEPSEEK_API_KEY`，并遵循两份标注配置中的缓存设置。

### 从 GitHub 克隆后准备文件

先安装 `requirements.txt` 中的依赖。仓库内已有 `data/gold150.jsonl`。将 [Zenodo 附录](https://doi.org/10.5281/zenodo.19562450) 解压到与 `SW-E-P/` 并列的 `AIReviewActionAnalysis(Zenodo)/`。确认附录的 `address_feature_matrix/` 下有这两个文件。

- `_selected_reviews_with_features/reviews_contains_valid_by_LLM_lda_topics_selected.csv`
- `labels/all_reviews_with_LLM_labels.csv`

`artifacts/` 由 Git 忽略。要复用小组的历史跑批，请从保存了产物的机器复制以下文件，保持它们在 `SW-E-P/` 下的相对路径。

| 文件 | 何时需要 |
| --- | --- |
| `artifacts/deepseek-paper/annotations.csv` 和 `artifacts/deepseek-v21/annotations.csv` | 复用已有标注时。缺失时可用 `--rerun-llm` 生成新标注 |
| `artifacts/rq3/all_reviews/rq3_metrics.json` 和 `artifacts/rq3/ai_only/rq3_metrics.json` | 复用已有 RQ3 指标时。缺失时可用 `--recompute` 本地重训 |
| `artifacts/rq3/all_reviews/rq3_feature_importance.csv` | 可选。标签灵敏度分析用它加入与历史全量模型的排名对照 |

如果只有两份历史标注 CSV，可用 `python run.py reproduce --recompute` 离线生成报告。
两类产物都缺失时，准备好 API key 后可执行 `python run.py reproduce --recompute --rerun-llm`。
入口会在开始运行前列出当前命令所缺的文件。仅需检查安装和数据加载时，可以运行 `python run.py validate-data -c config/config.gold150.yaml`。

## 2. 产物

`artifacts/reproduction/`（已被 `.gitignore` 忽略，随时可重生）：

| 文件 | 内容 |
| --- | --- |
| `report.md` | 可直接粘进报告的 Markdown：输入哈希、RQ2 四视角对照、分来源表、RQ3 指标与 SHAP 前十、四条结论的分组采纳率、标签灵敏度 |
| `manifest.json` | 同一批数字的机器可读版本，含 git commit、Python 与包版本、两个输入文件的 sha256 |
| `rq2-ab.json` | `compare_runs.py` 的完整输出（两 run 的逐视角指标、一致率、标签转移表） |
| `conclusions.json` | 四条结论的原始计数 |
| `label-sensitivity.json` | 两套标签的一致率与 κ、两次 RF 指标、SHAP 名次移动 |

`manifest.json` 里的 `commit` 与 SHA-256 可核对代码版本、gold 数据和特征矩阵。复核历史报告时还需使用相同的标注 CSV、RQ3 标签表和指标产物，并核对包版本。

## 3. 它复现了哪些结论

| 出处 | 数字 | 在哪一节 |
| --- | --- | --- |
| 论文 Table VII | 四个视角的 accuracy / macro-F1（v2、v2.1、论文三列） | `report.md` §RQ2 |
| 论文 Table XI / XII | 随机森林 3,879 条 与 2,990 条 AI-only 的两个指标 | §RQ3 |
| 论文 Table XI 的 SHAP 排序 | 全体与 AI-only 的 mean\|SHAP\| 前十 | §RQ3 |
| 论文 Table XIII–XVI | 触发方式、代码片段、评论长度、粒度的采纳率（全体与 AI-only 两套） | §RQ3 四条结论 |
| `docs/rq3-label-sensitivity.md` | 换标签后的一致率 92.7 %、κ 0.835、两次 RF 指标、SHAP 名次移动 3.78 | §RQ3 标签灵敏度 |
| `docs/rq2-results.md` | 两个 prompt 的一致性 130/150 = 86.7 %、其中 13 条 Stage-1 改变 | §RQ2 |

## 4. 已知的边界

- 默认模式读取 `artifacts/rq3/*/rq3_metrics.json`。需要用当前数据重训时，加 `--recompute`。
  重训结果写入 `artifacts/reproduction/rq3-all/` 和 `artifacts/reproduction/rq3-ai/`。RF 和 SHAP 使用固定随机种子，复核时应对照依赖版本。
- **`--rerun-llm` 不可能逐位复现**：模型服务端的浮点累加与批次调度不受我们控制
  （DEV-04 只跑单次而非论文的五次，DEV-09 换成了 DeepSeek flash）。同配置重跑会出现
  少量标签翻转，这正是 `--repeat` 存在的理由。
- **`report.md` 里的「论文」列是硬编码常量**（`PAPER` 字典，见脚本顶部）：它取自
  Table VII 的全体平均，改动时请对照 `docs/rq2-results.md` 的引用页码。
- **四个结论的 AI-only 视图没有 human 行**：Human 本来就被过滤掉了；两个视图里
  file-level / hunk-level 的计数之所以在过滤后不变，是因为 Human 不属于这两类。

## 5. 加一步新分析时

1. 让新步骤写一个 JSON 到 `artifacts/`（不要只 print）；
2. 在 `scripts/reproduce_all.py` 里加一个 `step_*()`，只读那个 JSON；
3. 在 `markdown()` 里加一节，并给 `tests/test_reproduce.py` 的 `_payload()` 补上对应键——
   那三个测试的作用就是防止某个键的形状变化把整份报告打崩。

