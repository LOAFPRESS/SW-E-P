# 一条命令复现全部数字

`scripts/reproduce_all.py` 把仓库里散在四个地方的数字收进同一个出口，避免写报告时
从五份文档里各抄一行、抄错一个小数点。

## 1. 三种模式

| 命令 | 做什么 | 花钱 | 用时 |
| --- | --- | --- | --- |
| `run.py reproduce` | 复用 `artifacts/` 里已有的标注结果与 RQ3 结果，重跑四个确定性的、几十秒的步骤，重新生成 `report.md` / `manifest.json` | 0 | ~15 s |
| `run.py reproduce --recompute` | 上面全部 + 重训随机森林（RQ3 全部 3,879 条 与 AI-only 2,990 条，含 SHAP） | 0 | 1–3 min |
| `run.py reproduce --rerun-llm` | 上面全部 + 重跑两个 prompt 的 150 条标注批次（`config/config.deepseek.yaml`、`config/config.deepseek-v21.yaml`） | ~$0.6 | ~40 min |

底层实现是 `scripts/reproduce_all.py`；`run.py reproduce` 只是转发这三个开关，
两种写法等价。

`--rerun-llm` 需要 `DEEPSEEK_API_KEY`；前两种模式不联网，适合在答辩机上现场演示。

## 2. 产物

`artifacts/reproduction/`（已被 `.gitignore` 忽略，随时可重生）：

| 文件 | 内容 |
| --- | --- |
| `report.md` | 可直接粘进报告的 Markdown：输入哈希、RQ2 四视角对照、分来源表、RQ3 指标与 SHAP 前十、四条结论的分组采纳率、标签灵敏度 |
| `manifest.json` | 同一批数字的机器可读版本，含 git commit、Python 与包版本、两个输入文件的 sha256 |
| `rq2-ab.json` | `compare_runs.py` 的完整输出（两 run 的逐视角指标、一致率、标签转移表） |
| `conclusions.json` | 四条结论的原始计数 |
| `label-sensitivity.json` | 两套标签的一致率与 κ、两次 RF 指标、SHAP 名次移动 |

`manifest.json` 里的 `commit` 与两个 sha256 是复现的锚点：只要这两条输入哈希不变，
`report.md` 里的数字就应该逐字重现。

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

- **默认模式不重算随机森林**：它读的是 `artifacts/rq3/*/rq3_metrics.json`。若怀疑那份 JSON
  过期，加 `--recompute`。SHAP 用固定 seed 与固定背景集，所以重算结果逐位一致。
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

