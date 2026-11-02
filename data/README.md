# 数据说明（标注模块的输入）

## 1. 数据来源：Zenodo 附录包（已在手）

论文的 150 条人工标注 gold 随论文以 Zenodo 数据集发布（附录 ① 10.5281/zenodo.19562449、
附录 ② 10.5281/zenodo.19562450）。**2026-11-02 用户已把附录包下载到本机**：

```
C:\Users\刘思懿\Documents\软件工程\P1\AIReviewActionAnalysis(Zenodo)
```

它不是仓库的一部分（体积大、且含论文作者的其他材料），仓库只保存由它派生出来的
`data/gold150.jsonl` 与 `data/gold150.provenance.json`。

`scripts/build_gold_dataset.py` 负责派生：

```powershell
.\.venv\Scripts\python.exe scripts\build_gold_dataset.py
# wrote 150 record(s) -> data/gold150.jsonl
# provenance -> data/gold150.provenance.json
```

参数：`--zenodo-root`（默认指向上面那个目录）、`--output`（默认 `data/gold150.jsonl`）、
`--sources file-level,hunk-level,human`。

### 1.1 构建规则（`src/swep/data/zenodo.py`）

- **输入**：`llm_analysis/input/sampled_file_level_review.csv`（50）、`sampled_hunk...` 实际文件名为
  `sampled_patch_level_review.csv`（50）、`sampled_human_review.csv`（50）。
- **标签**：`llm_analysis/labeled/(resolved)sampled_*_review.csv` 的 `Final Result` 列，
  按 `Comment_URL` 内连接（三个文件各 50/50 全中）。
- **标签码映射**：`0` → `None`、`1` → `General`、`2,-1` → `Valid-Uncertain`、`2,0` → `Valid-Unaddressed`、
  `2,1` → `Valid-Partially`、`2,2` → `Valid-Fully`；未知码直接报错（不静默丢弃）。
- **字段搬运**：`Body` → `comment_text`、`Diff_hunk` → `review_diff`、`Change_Until_Merged` →
  `subsequent_changes`、`Diff_path` → `reviewed_path`、`New_path` → `new_path`、`source_action` →
  `action_name`；`source` 由文件名决定（file-level / hunk-level / human）。
- **脏值归一**：`File_Deleted` 保留为哨兵（prompt 里表述为"文件在评审后被删除"）；
  字面量 `nan`、`N/A`、`<NA>`、空串统一成 `""`（**但 `File_Deleted` 不归一**）。
- **URL 解析**：同时解析 `Comment_URL`（`api.github.com/repos/{o}/{r}/pulls/comments/{id}`）与
  `Comment_HTML_URL`（`github.com/{o}/{r}/pull/{n}#discussion_r{id}`），合并得到 `repo` / `pr_number`。
- **可追溯性**（DOM-1.2/1.4）：`data/gold150.provenance.json` 记录每个源 CSV 的 SHA-256、
  标签码直方图、各来源计数、`deleted_file_rows`、`unlabeled`（URL 匹配不上的行号）等。

### 1.2 构建结果（2026-11-02 实测）

| 项 | 值 |
|----|----|
| 记录数 | 150（file-level 50 / hunk-level 50 / human 50） |
| 标签分布 | `None` 11、`General` 19、`Valid-Uncertain` 6、`Valid-Unaddressed` 43、`Valid-Partially` 13、`Valid-Fully 58` |
| Addressed（Partially + Fully） | 71 / 150 = 47.3% |
| `subsequent_changes` 为空 | 1 条（`nan`） |
| `File_Deleted` | 6 条 |
| 未匹配 URL | 0 |

> ⚠️ 这里的 Addressed 47.3% 与论文 RQ3 描述的 25.1% 不一致，原因待核，
> 见 `docs/paper-deviations.md` 的 **DEV-10**。标注六分类不受影响。

## 2. 合成样例（仅冒烟用）

`data/samples/sample_comments.jsonl` 是 12 条**合成**记录（`synthetic: true`），覆盖三种来源与六类标签、
有/无 `review_diff`、有/无 `subsequent_changes`。它只用来验证"读取 → 两阶段推理 → CSV 导出 → 指标"
整条链路在**无数据、无网络、无 key**时也能跑通，**不要用它报告准确率**。

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
| `subsequent_changes` | 评论之后该文件的修改，Stage-2 判断依据（`File_Deleted` 有特殊语义） |
| `reviewed_path` / `new_path` | 被评审的文件路径 / 重命名后的路径（原版 prompt 的 `reviewed_path`） |
| `action_id` / `action_name` | 触发的 GitHub Action |
| `trigger` | `automatic`（push/pull_request）或 `manual`（workflow_dispatch） |
| `granularity` | `file` / `hunk` |
| `repo` / `pr_number` | 仓库与 PR 编号 |
| `gold_label` / `gold_issues` | 人工标注（仅评估用，不进入 prompt） |
| `synthetic` | 是否为合成数据 |

### 3.1 列名自动适配（换数据源时用）

`gold150.jsonl` 已经是内部字段名，不需要映射。只有当你直接喂 Zenodo 原始 CSV 或其他版本的 CSV 时，
才需要 `data.column_map`。读取时先按内部字段名找列，再按别名找（不区分大小写、下划线/空格/连字符等价）：

| 内部字段 | 可识别的原始列名（部分） |
|----------|--------------------------|
| `comment_id` | `commentid`、`id`、`comment id`、`review_comment_id` |
| `source` | `comment_source`、`origin`、`level` |
| `comment_text` | `comment`、`comment_body`、`body`、`review_comment`、`text` |
| `review_diff` | `diff`、`code_diff`、`reviewed_changes` |
| `subsequent_changes` | `subsequent_modifications`、`later_changes`、`subsequent_diff` |
| `reviewed_path` | `review_path`、`diff_path`、`path`、`reviewed_file`、`file_path` |
| `new_path` | `file_name`、`new_file_path`、`renamed_path` |
| `gold_label` | `human_label`、`label`、`annotation`、`true_label` |
| `trigger` | `trigger_type`、`event` |
| `granularity` | `review_granularity` |
| `repo` | `repository`、`repo_name`、`full_name` |
| `pr_number` | `pr`、`pull_number`、`pull_request` |

显式映射优先级更高：

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
.\.venv\Scripts\python.exe run.py validate-data -c config/config.gold150.yaml
# dataset: .../data/gold150.jsonl
# records: 150
#   file-level   50
#   hunk-level   50
#   human        50
#   with review diff: 150
#   with reviewed path: 150
#   with subsequent changes: 149
#   with gold label: 150
```

出错时会打印 `Available columns: [...]`，直接把真实列名抄进 `column_map` 即可。
