# 数据说明（标注模块的输入）

## 1. 期望的数据来源

论文的 150 条人工标注 gold 样本随论文以 Zenodo 数据集发布（附录 ① 10.5281/zenodo.19562449、
附录 ② 10.5281/zenodo.19562450）。**截至 2026-11-02，本机网络无法访问 `zenodo.org`**
（TCP 超时，代理与 `web_fetch` 均失败），因此工作区内没有原始 CSV；偏差登记见
`docs/paper-deviations.md` 的 DEV-01 / DEV-02。

拿到 CSV 后放进 `data/raw/`（已在 `.gitignore` 中忽略，避免把大文件提交进仓库）。

## 2. 合成样例（当前默认）

`data/samples/sample_comments.jsonl` 是 12 条**合成**记录（`synthetic: true`），
覆盖：

- 三种来源：`file-level` 6 条、`hunk-level` 4 条、`human` 2 条；
- 六类标签：`None`、`General`、`Valid-*` 四档；
- 有/无 `review_diff`、有/无 `subsequent_changes` 的组合。

它只用来验证"读取 → 两阶段推理 → CSV 导出 → 指标"整条链路，**不要用它报告准确率**。

## 3. 字段约定

必需字段（缺失会在 `run.py validate-data` 阶段报错并列出可用列）：

| 字段 | 含义 |
|------|------|
| `comment_id` | 评论唯一 ID |
| `source` | `file-level` / `hunk-level` / `human` |
| `comment_text` | 评论文本 |

可选字段（有则用于 prompt 上下文与统计）：

| 字段 | 含义 |
|------|------|
| `review_diff` | 评论针对的改动（diff/hunk），Stage-1 上下文 |
| `subsequent_changes` | 评论之后该文件的修改，Stage-2 判断依据 |
| `action_id` / `action_name` | 触发的 GitHub Action |
| `trigger` | `automatic`（push/pull_request）或 `manual`（workflow_dispatch） |
| `granularity` | `file` / `hunk` |
| `repo` / `pr_number` | 仓库与 PR 编号 |
| `gold_label` / `gold_issues` | 人工标注（仅评估用，不进入 prompt） |
| `synthetic` | 是否为合成数据 |

### 3.1 列名自动适配

读取时先按内部字段名找列，再按别名找（不区分大小写、下划线/空格/连字符等价），
所以 Zenodo CSV 的列名大概率可以直接读。已内置的别名：

| 内部字段 | 可识别的原始列名（部分） |
|----------|--------------------------|
| `comment_id` | `commentid`、`id`、`comment id`、`review_comment_id` |
| `source` | `comment_source`、`origin`、`level` |
| `comment_text` | `comment`、`comment_body`、`body`、`review_comment`、`text` |
| `review_diff` | `diff`、`code_diff`、`reviewed_changes` |
| `subsequent_changes` | `subsequent_modifications`、`later_changes`、`subsequent_diff` |
| `gold_label` | `human_label`、`label`、`annotation`、`true_label` |
| `trigger` | `trigger_type`、`event` |
| `granularity` | `review_granularity` |
| `repo` | `repository`、`repo_name`、`full_name` |
| `pr_number` | `pr`、`pull_number`、`pull_request` |

### 3.2 显式映射（别名不够时）

在 `config/config.yaml` 里写 `data.column_map`，优先级高于别名：

```yaml
data:
  path: "data/raw/gold150.csv"
  format: csv
  column_map:
    comment_id: "review_comment_id"      # 或写成候选列表 ["review_comment_id", "id"]
    comment_text: "comment_body"
    review_diff: "code_diff"
    subsequent_changes: ["later_changes", "subsequent_diff"]
    source: "level"
```

## 4. 快速检查

```powershell
.\.venv\Scripts\python.exe run.py validate-data -c config/config.yaml
# dataset: .../gold150.csv
# records: 150
#   file-level   50
#   hunk-level   50
#   human        50
```

出错时会打印 `Available columns: [...]`，直接把真实列名抄进 `column_map` 即可。
