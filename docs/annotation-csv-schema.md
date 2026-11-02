# `annotations.csv` 数据契约（21 列）

> 本文件是标注模块（刘思懿）与数据/评估模块（尹捷睿）、ML 模块（杨弋驰）之间的接口约定。
> 对应 URS REQ-1.8「标注 CSV 固定 schema」；列顺序在 `swep.schema.CSV_COLUMNS` 中定义，**改动必须同步本文件并 bump 版本**。

## 1. 列字典

| # | 列名 | 类型 | 说明 |
|---|------|------|------|
| 1 | `comment_id` | str | 评论唯一 ID，与输入数据集一致，作为 join key |
| 2 | `source` | str | 评论来源：`file-level` / `hunk-level` / `human`（论文 150 条 gold 各 50 条） |
| 3 | `stage1_label` | enum | Stage-1 判定：`None` / `General` / `Valid` |
| 4 | `stage1_issues` | str | Stage-1 抽取的可执行问题清单，多个条目用 `" \| "` 连接 |
| 5 | `stage2_label` | enum/空 | Stage-2 判定：`Valid-Uncertain` / `Valid-Unaddressed` / `Valid-Partially` / `Valid-Fully`；Stage-1 非 `Valid` 时为空 |
| 6 | `final_label` | enum | 六类最终标签（Stage-1 非 Valid 时= `stage1_label`；Valid 时= `stage2_label`；Valid 但缺 Stage-2 记为 `Valid-Uncertain`） |
| 7 | `is_addressed` | 0/1 | 二分类视图：`final_label ∈ {Valid-Partially, Valid-Fully}` → 1，否则 0（失败行为 0） |
| 8 | `stage1_rationale` | str | Stage-1 模型给出的判定理由（调试/审计用） |
| 9 | `stage2_rationale` | str | Stage-2 模型给出的判定理由 |
| 10 | `addressed_items` | str | Stage-2 判定"已解决"的问题条目，`" \| "` 连接 |
| 11 | `unaddressed_items` | str | Stage-2 判定"未解决"的问题条目，`" \| "` 连接 |
| 12 | `model_stage1` | str | Stage-1 实际使用的模型名（来自配置） |
| 13 | `model_stage2` | str | Stage-2 实际使用的模型名；未调用 Stage-2 时为空 |
| 14 | `prompt_version` | str | prompt 版本号；与 `summary.json` 的 `run_fingerprint` 一起用于可追溯（DOM-1.4） |
| 15 | `input_tokens` | int | 该条记录所有调用（含修复重问）的输入 token 合计 |
| 16 | `output_tokens` | int | 输出 token 合计 |
| 17 | `cost_usd` | float | 该条记录的费用合计（美元，6 位小数） |
| 18 | `cached_calls` | int | 命中缓存的调用次数（0 表示全部真实调用） |
| 19 | `attempts` | int | 首次请求之后的重试次数（含解析修复时的重问） |
| 20 | `latency_ms` | float | 该条记录累计调用耗时（毫秒） |
| 21 | `error` | str | 失败原因；为空表示该条成功。失败行其余标签列为空、`is_addressed=0` |

## 2. 标签定义（论文 §IV-B）

**Stage-1（有效性）**

- `None`：纯粹的表扬、寒暄、无内容的社交性评论，不含任何问题或建议。
- `General`：提出改进方向但过于笼统（"improve readability"），无法从中提取可执行动作。
- `Valid`：至少包含一个**具体、可执行**的问题或建议（点名具体函数/变量/行为）。

**Stage-2（采纳，仅对 Valid）**

- `Valid-Uncertain`：信息不足，无法判断（文件被删除、改动过大、后续修改缺失）。
- `Valid-Unaddressed`：清单中的问题一个都没被后续修改解决。
- `Valid-Partially`：解决了一部分。
- `Valid-Fully`：全部解决（"解决"指实现了评论要求的改动，而不是恰好改到相邻行）。

**二分类**（论文 RQ3 / RF 训练目标）

`Addressed = Valid-Partially ∪ Valid-Fully`，其余（含 `None`/`General`/`Unaddressed`/`Uncertain`）为 `Not-Addressed`。

## 3. 使用示例

```python
import pandas as pd

df = pd.read_csv("artifacts/annotations.csv", keep_default_na=False)

# 只保留成功行参与评估
ok = df[df["error"] == ""].copy()

# 六类分布（论文 Table VII 的六类口径）
print(ok["final_label"].value_counts())

# 二分类目标（RQ3）
ok["addressed"] = ok["is_addressed"].astype(int)

# 分层统计：file-level / hunk-level / human
print(ok.groupby("source")["is_addressed"].mean())
```

## 4. 注意事项

1. **一行一条记录**，不重复。缓存命中的行同样写出（`cached_calls > 0`、`cost_usd = 0`）。
2. `" | "` 是本模块约定的列表分隔符；条目内部若出现 `|` 不会被转义，因此下游如需精细拆分，
   请以 `stage1_issues`/`addressed_items` 的字符串为准再做一次人工确认。
3. **失败行必须过滤**：`error != ""` 的行标签为空，直接参与准确率会引入假阴性。
4. 列顺序固定；追加新列属于接口变更，需通知组长与杨弋驰，并同步 `docs/annotation-pipeline.md`。
