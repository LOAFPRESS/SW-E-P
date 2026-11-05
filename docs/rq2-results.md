# RQ2 · 真实模型标注结果（150 条 gold，DeepSeek）

> 本次运行：2026-11-05 10:00–10:15，`config/config.deepseek.yaml`，
> prompt `v2-paper-2026-11`（论文附录原文，`format: text`），
> `run_fingerprint = 07faac198688`。产物在 `artifacts/deepseek-paper/`。

## 1. 运行记录

| 项 | 值 |
| --- | --- |
| 模型 | Stage-1 `deepseek-flash`（`reasoning_effort: none`）、Stage-2 `deepseek-flash`（`reasoning_effort: high`） |
| 样本 | 150 条 gold（file-level 50 / hunk-level 50 / human 50） |
| 调用 | 262 次（Stage-1 150 + Stage-2 112），0 重试、0 解析修复、0 失败 |
| token | 295,501 输入 / 126,183 输出 |
| 费用 | **$0.2401**（预算上限 $5.00） |
| 用时 | 888 s（串行，约 15 分钟） |
| 产物 | `annotations.csv`（21 列）、`summary.json`、`run_report.md`、`requests.jsonl`、`run.log` |

一次跑完、零失败，说明流水线（重试、缓存、预算、审计）在真实 provider 上是通的；
`requests.jsonl` 里每次调用都有 prompt 版本、token 与费用，可追溯（DOM-1.4）。

## 2. 与论文 Table VII 对照

论文用的是 GPT-4.1（Stage-1）+ o3-mini（Stage-2）。我们是 DeepSeek 替代（DEV-09），
因此差距同时包含"prompt 移植"与"模型能力"两个因素，不能直接归因。

### 2.1 四个视角

| 视角 | n | 本项目 Acc / Macro-F1 | 论文 Acc / Macro-F1 | 差（Acc） |
| --- | --- | --- | --- | --- |
| Stage-1（None/General/Valid） | 150 | 87.3% / 74.8% | 94.5% / 90.8% | **-7.2 pp** |
| Stage-2（四档 addressing） | 109 | 87.2% / 86.6% | 91.8% / 88.5% | -4.6 pp |
| 六类最终标签 | 150 | 78.0% / 76.8% | 86.1% / 74.6% | -8.1 pp |
| 二分类（Addressed vs 其它） | 150 | **91.3% / 91.3%** | 91.5% / 89.8% | -0.2 pp |

**关键结论：二分类几乎完全对齐（91.3% vs 91.5%，Macro-F1 甚至高 1.5 pp）。**
说明"这条评论最终有没有被采纳"这个核心判断是成功迁移的；六分类的差距集中在
None / General / Valid-Unaddressed 这几个相邻档位的边界上。

### 2.2 分来源（六类 / 二分类）

| 来源 | n | 六类 Acc / F1 | 论文六类 | 二分类 Acc / F1 |
| --- | --- | --- | --- | --- |
| file-level | 50 | 62.0% / 44.0% | 83.6% / 78.1% | 92.0% / 90.5% |
| hunk-level | 50 | 82.0% / 76.2% | 89.2% / 83.4% | 92.0% / 91.5% |
| human | 50 | **90.0% / 72.6%** | 85.6% / 62.4% | 90.0% / 86.7% |

- **human 组超过论文**（90.0% vs 85.6%，F1 72.6 vs 62.4）：人类评论语义清晰，
  DeepSeek 判断稳定。
- **file-level 组是主要失分点**（62.0% vs 83.6%，F1 44.0 vs 78.1）：
  但它的二分类仍有 92.0%，说明"哪个文件级评论被采纳"判对了，错的是**六类档位**。
- file-level 的 Macro-F1 偏低还有样本因素：该组 gold 里 `Valid-Fully` 只有 2 条、
  `Valid-Uncertain` 为 0，单类失误会把 macro 平均值拉得很低。

## 3. 逐类精确率/召回率（六类，n=150）

| 类别 | support | precision | recall | F1 |
| --- | --- | --- | --- | --- |
| None | 11 | 0.556 | **0.909** | 0.690 |
| General | 19 | 0.600 | 0.632 | 0.615 |
| Valid-Uncertain | 6 | 1.000 | 1.000 | 1.000 |
| Valid-Unaddressed | 43 | 0.853 | 0.674 | 0.753 |
| Valid-Partially | 13 | 0.588 | 0.769 | 0.667 |
| Valid-Fully | 58 | 0.909 | 0.862 | 0.885 |

## 4. 错误分析（混淆矩阵里最主要的四条）

1. **gold `Valid-Unaddressed` → 预测 `General`（6 条）**：把"有具体建议但没被采纳"
   降级成"太泛化"。这是 file-level 组的头号错误（该组 21 条 Unaddressed 里错了 9 条）。
   推测原因：文件级评论的 diff 是整份文件，模型难以确认"建议是否指向文件里的一行"，
   于是退回 General。
2. **gold `None` → 预测 `General`（5 条）**：把赞美/已实现的描述当成泛化建议。
3. **gold `General` → 预测 `None`（5 条）**：反向的过度严格。
4. **`Valid-Partially` ↔ `Valid-Fully`（3 + 2 条）**：档位内部边界，影响小于前三条。

Stage-1 层面的错误分布（gold → pred）：Valid→Valid 109、General→General 12、None→None 10、
Valid→General 8、General→None 5、Valid→None 3、General→Valid 2、None→Valid 1。
即 Stage-1 的 87.3% 主要输在 **Valid↔General** 与 **General↔None** 两条边界。

## 5. 与论文的差距怎么解释

- **二分类对上、六分类偏下**这个组合本身是有信息量的：论文的四条结论
  （简洁评论、含代码片段、手动触发、hunk 级更易被采纳）都建立在二分类/RQ3 上，
  我们的二分类复现成功，因此**结论层面的复现不受六分类差距影响**。
- Stage-1 是主要瓶颈（87.3% vs 94.5%），而 Stage-2 只差 4.6 pp。
  附录里 Stage-1 也用非推理模型（GPT-4.1），我们同样关了思考，条件对齐；
  差别在模型本身（DeepSeek-flash 对"泛化 vs 具体"的判定更宽松）。
- 六分类 Macro-F1 反而比论文高 2.2 pp（76.8 vs 74.6）：我们在少数类
  （Uncertain、Partially）上更均衡，但整体准确率被上面三条边界错误拖低。

## 6. 下一步（按优先级）

1. **prompt 迭代 v2.1（针对性）**：只改 Stage-1 的"具体 vs 泛化"判定说明，
   显式要求"必须能把建议落到 reviewed file 的具体行/标识符上才算 Valid，
   否则 General"，并把 file-level 的判定示例写进模板；改完 bump 版本号，
   用同一批 150 条重跑，与新基线对比（成本约 $0.24、15 分钟）。
2. **稳定性**：`--repeat 5` 看同一配置下的标签一致率（DEV-04 的"论文跑 5 次"口径）。
3. **分类别报告**：把混淆矩阵与 per-class 表放进最终报告的 RQ2 小节，
   明确写"六分类差距来自档位边界，二分类已对齐"。

## 7. 复现方式

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."     # 只在终端里，不要写进文件
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --write-report
.\.venv\Scripts\python.exe scripts\compare_with_paper.py artifacts\deepseek-paper\annotations.csv
```

`scripts/compare_with_paper.py` 会打印上面 2.1 / 2.2 的两张表（论文数字写在脚本的
`PAPER` 常量里，改论文版本时同步修改）。
