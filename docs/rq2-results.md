# RQ2 · 真实模型标注结果（150 条 gold，DeepSeek）

两次运行、同一批 150 条 gold：

| 运行 | 配置 | prompt | fingerprint | 产物 |
| --- | --- | --- | --- | --- |
| **v2（基线）** | `config/config.deepseek.yaml` | `v2-paper-2026-11`（附录原文） | `07faac198688` | `artifacts/deepseek-paper/` |
| **v2.1（A/B）** | `config/config.deepseek-v21.yaml` | `v2.1-guidance-2026-11-09`（原文 + 四条消歧规则，只改 Stage-1） | `b07c5940dfe9` | `artifacts/deepseek-v21/` |

> 论文用的是 GPT-4.1（Stage-1）+ o3-mini（Stage-2），本项目用 DeepSeek 替代（DEV-09），
> 因此差距同时包含"prompt 移植"与"模型能力"两个因素；v2.1 的四条规则是**看过这 150 条错误后写的**
> （DEV-13），提升属于样本内调参、偏乐观，引用时必须写明。

## 1. 运行记录

| 项 | v2 | v2.1 |
| --- | --- | --- |
| 模型 | Stage-1 `deepseek-flash`（`reasoning_effort: none`）、Stage-2 `deepseek-flash`（`high`） | 同左 |
| 样本 | 150 条 gold（file-level 50 / hunk-level 50 / human 50） | 同左 |
| 调用 | 262 次（150 + 112），0 重试、0 解析修复、0 失败 | 265 次（150 + 115），0 重试、0 解析修复、0 失败 |
| token | 295,501 输入 / 126,183 输出 | 333,793 输入 / 163,355 输出 |
| 费用 | **$0.2401** | **$0.2962** |
| 用时 | 888 s（约 15 分钟） | 1257 s（约 21 分钟） |
| 产物 | `annotations.csv`、`summary.json`、`run_report.md`、`requests.jsonl`、`run.log` | 同左 |

两次都是一次跑完、零失败，说明流水线（重试、缓存、预算、审计）在真实 provider 上是通的；
`requests.jsonl` 里每次调用都有 prompt 版本、token 与费用，可追溯（DOM-1.4）。

## 2. 与论文 Table VII 对照

### 2.1 四个视角

| 视角 | n | v2 Acc / F1 | v2.1 Acc / F1 | 论文 Acc / F1 | v2.1 与论文差 |
| --- | --- | --- | --- | --- | --- |
| Stage-1（None/General/Valid） | 150 | 87.3% / 74.8% | **91.3% / 80.8%** | 94.5% / 90.8% | -3.2 pp / -10.0 pp |
| Stage-2（四档 addressing） | 109 | 87.2% / 86.6% | 86.7% / 86.3% | 91.8% / 88.5% | -5.1 pp / -2.2 pp |
| 六类最终标签 | 150 | 78.0% / 76.8% | **81.3% / 80.1%** | 86.1% / 74.6% | -4.8 pp / **+5.5 pp** |
| 二分类（Addressed vs 其它） | 150 | 91.3% / 91.3% | **91.3% / 91.3%** | 91.5% / 89.8% | -0.2 pp / **+1.5 pp** |

**两个稳定的结论在 A/B 前后都没变：**
1. **二分类几乎完全对齐**（91.3% vs 论文 91.5%，Macro-F1 高 1.5 pp）——
   "这条评论最终有没有被采纳"这个核心判断是成功迁移的。
2. **六分类准确率偏低、但 Macro-F1 反超论文**（80.1 vs 74.6）——
   差距集中在 None / General / Valid-Unaddressed / Valid-Partially 这些相邻档位的边界上，
   而不是整体偏一个方向。

### 2.2 分来源（六类 / 二分类）

| 来源 | n | v2 六类 | v2.1 六类 | 论文六类 | v2.1 二分类 |
| --- | --- | --- | --- | --- | --- |
| file-level | 50 | 62.0% / 52.8% | **74.0% / 62.5%** | 83.6% / 78.1% | 92.0% / 90.5% |
| hunk-level | 50 | 82.0% / 76.2% | 80.0% / 74.7% | 89.2% / 83.4% | 88.0% / 87.7% |
| human | 50 | 90.0% / 72.6% | 90.0% / 68.5% | 85.6% / 62.4% | **94.0% / 91.5%** |

- **file-level 是 v2.1 的最大受益者**（六类 62.0% → 74.0%，F1 52.8 → 62.5）：
  四条规则里的"含糊措辞本身不算 general"正是针对该组的头号错误。
- **hunk-level 略降**（六类 82.0% → 80.0%，二分类 92.0% → 88.0%）：该组有 4 条评论的二分类
  判定翻转，其中 3 条是错误翻转（把 gold `Valid-Unaddressed` 抬成 Addressed），
  1 条是修正，净 -2 条。这是规则放宽在 hunk 级上的副作用，50 条的样本量把它放大成 -4 pp。
- **human 组六类不变、二分类升到 94.0%**（2 条翻转都对）：其 Macro-F1 仍高于论文
  （68.5 vs 62.4），human 组 gold 里 `Valid-Fully` 占 39/50，档位内部边界错得多时
  macro 会被明显拉低。
- file-level 的 Macro-F1 偏低还有样本因素：该组 gold 里 `Valid-Fully` 只有 2 条、
  `Valid-Uncertain` 为 0，单类失误会把 macro 平均值拉得很低。

## 3. 逐类精确率/召回率（六类，n=150）

| 类别 | support | v2 P / R / F1 | v2.1 P / R / F1 |
| --- | --- | --- | --- |
| None | 11 | 0.556 / 0.909 / 0.690 | 0.600 / 0.818 / 0.692 |
| General | 19 | 0.600 / 0.632 / 0.615 | **0.750 / 0.789 / 0.769** |
| Valid-Uncertain | 6 | 1.000 / 1.000 / 1.000 | 1.000 / 1.000 / 1.000 |
| Valid-Unaddressed | 43 | 0.853 / 0.674 / 0.753 | **0.935 / 0.674 / 0.784** |
| Valid-Partially | 13 | 0.588 / 0.769 / 0.667 | 0.550 / 0.846 / 0.667 |
| Valid-Fully | 58 | 0.909 / 0.862 / 0.885 | 0.897 / 0.897 / 0.897 |

v2.1 把收益几乎全花在 **General（F1 0.615 → 0.769）** 上：精确率 0.600 → 0.750 说明
"不再是垃圾桶类"，recall 也升到 0.789。代价是 `Valid-Partially` 精确率微降
（0.588 → 0.550）、`None` 召回从 0.909 降到 0.818（有 1 条 None 被抬成 Valid-Fully）。

## 4. 错误分析

v2 的六类错误（混淆矩阵里最主要的四条）：

1. **gold `Valid-Unaddressed` → 预测 `General`（6 条）**：把"有具体建议但没被采纳"
   降级成"太泛化"。这是 file-level 组的头号错误（该组 21 条 Unaddressed 里错了 9 条）。
   推测原因：文件级评论的 diff 是整份文件，模型难以确认"建议是否指向文件里的一行"，
   于是退回 General。
2. **gold `None` → 预测 `General`（5 条）**：把赞美/已实现的描述当成泛化建议。
3. **gold `General` → 预测 `None`（5 条）**：反向的过度严格。
4. **`Valid-Partially` ↔ `Valid-Fully`（3 + 2 条）**：档位内部边界，影响小于前三条。

v2 的 Stage-1 错误分布（gold → pred）：Valid→Valid 109、General→General 12、None→None 10、
Valid→General 8、General→None 5、Valid→None 3、General→Valid 2、None→Valid 1。

v2.1 的 Stage-1 错误分布：Valid→Valid 113、General→General 15、None→None 9、
Valid→General 4、General→None 3、Valid→None 3、General→Valid 1、None→Valid 1、None→General 1。
即两条主边界都被压窄：**Valid→General 8 → 4**、**General→None 5 → 3**，
同时 General 类的召回从 0.632 升到 0.789（gold General 的 19 条里有 15 条判对）。
残留错误集中在"该判 Valid 却判 General/None"（Valid→General 4 + Valid→None 3 = 7 条），
即仍有 7 条具体建议被当成"太泛"或"没有问题"。

### 4.1 A/B 一致性（v2 vs v2.1，同一批 150 条）

- 六类最终标签一致 **130/150 = 86.7%**，其中 **13 条 Stage-1 标签发生变化**。
- 变化方向（v2 → v2.1，n）：`None→General` 4、`General→Valid-Unaddressed` 3、
  `Valid-Unaddressed→General` 2、`General→None` 2、`Valid-Unaddressed→Valid-Partially` 2、
  `Valid-Unaddressed→Valid-Fully` 2、`Valid-Fully→Valid-Partially` 2、
  `General→Valid-Fully` 1、`None→Valid-Fully` 1、`Valid-Partially→Valid-Fully` 1。
- 净效果：Stage-1 准确率 87.3% → 91.3%（+4.0 pp），六类 +3.3 pp，二分类**完全没动**（91.3%）。
  这说明四条规则修正的是"档位判定"，没有改变"是否被采纳"这个二元结论——
  对 RQ3（用二分类标签建模）而言是零风险改动。

## 5. 与论文的差距怎么解释

- **二分类对上、六分类偏下**这个组合本身是有信息量的：论文的四条结论
  （简洁评论、含代码片段、手动触发、hunk 级更易被采纳）都建立在二分类/RQ3 上，
  我们的二分类复现成功，因此**结论层面的复现不受六分类差距影响**。
- Stage-1 仍是主要瓶颈（v2.1 91.3% vs 论文 94.5%），Stage-2 差 5.1 pp。
  附录里 Stage-1 也用非推理模型（GPT-4.1），我们同样关了思考，条件对齐；
  剩余差距更可能来自模型本身（DeepSeek-flash 对"泛化 vs 具体"的判定仍偏宽松/偏严并存：
  残留 7 条该判 Valid 的判成 General/None，同时 1 条 General 被判成 Valid）。
- 六分类 Macro-F1 比论文高 5.5 pp（80.1 vs 74.6）：我们在少数类
  （Uncertain、Partially、Unaddressed）上更均衡，但整体准确率被档位边界拖低。
- 这份结果**不能**写成"我们的 pipeline 达到论文水平"，只能说：
  **二分类判定与论文持平，六分类档位判定略低，prompt 移植本身是通的。**

## 6. 下一步（按优先级）

1. **稳定性**：`--repeat 5` 看同一配置下的标签一致率（DEV-04 的"论文跑 5 次"口径，
   成本约 $1.2 / 75 分钟）。当前 v2.1 单次结果的置信区间未知，这是最该补的一块。
2. **held-out 复核**（DEV-13 缓解项）：按来源分层留出 30 条（各 10 条），
   用剩下 120 条做 prompt 选择、30 条只测一次，看 v2.1 的提升是否还在。
3. **分类别报告**：把混淆矩阵与 per-class 表放进最终报告的 RQ2 小节，
   明确写"六分类差距来自档位边界，二分类已对齐"。

## 7. 复现方式

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."     # 只在终端里，不要写进文件

# v2 基线
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml `
    --no-cache --write-report --output-dir artifacts\deepseek-paper

# v2.1 A/B
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek-v21.yaml `
    --no-cache --write-report --output-dir artifacts\deepseek-v21

# 与论文对照 / 两次运行互相对照
.\.venv\Scripts\python.exe scripts\compare_with_paper.py artifacts\deepseek-v21\annotations.csv
.\.venv\Scripts\python.exe scripts\compare_runs.py `
    artifacts\deepseek-paper\annotations.csv artifacts\deepseek-v21\annotations.csv `
    --labels v2 v2.1 --json artifacts\rq2-ab.json
```

`scripts/compare_with_paper.py` 会打印 §2.1 / §2.2 的两张表（论文数字写在脚本的
`PAPER` 常量里，改论文版本时同步修改）；`scripts/compare_runs.py` 输出 §4.1 的
对照表与转移矩阵（`--json` 会把全部数字落盘）。
