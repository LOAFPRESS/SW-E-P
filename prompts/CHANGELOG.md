# Prompt 变更日志

> 依据 DOM-1.2：任何 prompt 改动都要在这里留痕，并同步 `config/config.yaml` 的 `prompts.version`。
> 版本号会写进 `annotations.csv` 的 `prompt_version` 列，`summary.json` 的 `run_fingerprint`
> 还包含两个模板的 sha256 前缀，因此"哪一版 prompt 产出了哪批标签"是可追溯的。

## v2.1-guidance-2026-11-09（2026-11-09，刘思懿）· Stage-1 边界补充

**背景**：v2（附录原文）在 150 条 gold 上 Stage-1 只有 87.3% / macro-F1 74.8%（论文 94.5 / 90.8），
错误集中在三类（见 `docs/rq2-results.md` 的错误分析）：

- gold `General` 被判成 `None`：评论先写"没发现严重问题"，再列"加注释/统一命名"这类改进建议；
- gold `Valid-Unaddressed` 被判成 `General`：建议用了 "could be improved / consider" 这类措辞，但其实点了具体符号；
- gold `General` 被判成 `Valid`：先复述补丁做了什么，再给泛泛建议。

**改动**（仅 Stage-1；Stage-2 保持 v2 原文，以便 A/B 只隔离出 Stage-1 的影响）

- 新增 `prompts/stage1_v2_1_guidance.md`：在附录原文的分类说明之前插入四条消歧规则（不改动原文措辞）：
  1. "没发现严重问题 + 仍列出改进建议"算 general，不得判 `None`；只有"纯表扬 / 复述改动 / 只说代码没问题且不提要求"才是 `None`；
  2. 措辞含糊（could be improved / consider）本身不构成 general；只要点了具体位置、函数、变量、配置键或具体改法，就算 valid；
  3. 复述补丁内容的段落是描述，不是 item，也不影响其它建议的归类；
  4. 很短的评论只要对着 Reviewed Change 看是在要求具体修改，就算 valid。
- 新增 `config/config.deepseek-v21.yaml`：`prompts.stage1` 指向新模板、`version: v2.1-guidance-2026-11-09`，
  其余（模型、价格、预算、缓存路径）与 `config.deepseek.yaml` 完全一致，保证两次运行可比。

**为什么只写规则、不写示例**：示例若取自这 150 条 gold，等于把测试集泄漏进 prompt，因此只写措辞规则（DEV-13）。

**A/B 结果**（2026-11-09，同一批 150 条 gold，`artifacts/deepseek-v21/`，fingerprint `b07c5940dfe9`）：

| 视角 | v2（原文） | v2.1（+四条规则） | 变化 |
| --- | --- | --- | --- |
| Stage-1 Acc / Macro-F1 | 87.3% / 74.8% | **91.3% / 80.8%** | +4.0 / +6.0 pp |
| 六类 Acc / Macro-F1 | 78.0% / 76.8% | **81.3% / 80.1%** | +3.3 / +3.3 pp |
| 二分类 Acc / Macro-F1 | 91.3% / 91.3% | 91.3% / 91.3% | 不变 |
| file-level 六类 | 62.0% / 52.8% | **74.0% / 62.5%** | +12.0 / +9.7 pp |

- 收益集中在 General 类（F1 0.615 → 0.769）与 file-level 组；hunk-level 二分类退 4 pp（4 条翻转、3 条错）。
- 六类一致率 130/150 = 86.7%，13 条 Stage-1 标签变化；二分类一条没变。
- **注意**：规则是看着这批 150 条的错误写的（DEV-13），提升属样本内、偏乐观，引用时必须写明。
- 完整数字、逐类表、错误分布见 `docs/rq2-results.md`；复算命令 `scripts/compare_runs.py`。

## v2-paper-2026-11（2026-11-02，刘思懿）· 论文附录原文

**背景**：用户把 Zenodo 附录包下载到本机，原版 prompt 已从附录代码中取出并**逐字**落盘：

| 模板 | 来源文件 | 来源常量 |
| --- | --- | --- |
| `prompts/stage1_v2_original.md` | `llm_analysis/extract_suggestion_prompter_3.py` | `task_description_for_indentify_suggestion_12` |
| `prompts/stage2_v2_original.md` | `llm_analysis/analyze_addressed_prompter_4.py` | `task_description_for_analyze_addressed_7` |

**与 v1 的差别**

- 输出格式：原版是**纯文本**，不是 JSON —— `prompts.format: text`；`swep.llm.parsing` 用
  `parse_stage1_text` / `parse_stage2_text` 按附录 `extract_suggestion.py` /
  `analyze_addressed_status.py` 的规则解析（定位 `Classification:`，取其后最早出现的分类短语）。
- 输入内联：原版把三个字段用 `json.dumps(value, ensure_ascii=False)` 转义后填进 `Code Review:`；
  `builder._json_literal()` 复刻这一行为（换行/引号不会破坏结构）。
- 占位符：`$reviewed_path` `$reviewed_change` `$review_comment` / `$review_comment_items`
  `$subsequent_changes_block`。
- Stage-2 的 `Subsequent Code Changes:` 段由 `builder.describe_code_change()` 生成（无改动 / 文件被删除
  `File_Deleted` / 重命名 / 普通累积 diff 四种语义）；附录未公开该函数逐字措辞，属重建（DEV-01）。
- 系统提示词同样非原文（附录只有 user 侧模板），当前为一句话角色设定。

**使用方式**

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --dry-run
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --write-report
```

`config/config.qwen.yaml` 是同一套模板换 DashScope 端点；`config/config.gold150.yaml` 用 v1 模板 + mock
在真实 150 条 gold 上做离线冒烟。

**已知差异 / 待办**

1. `describe_code_change` 的措辞为重建（见 DEV-01 的"残余重建"段）；拿到原文后替换并 bump 版本。
2. system message 非原文。
3. 截断上限（`MAX_*_CHARS`）为本项目自定，论文未说明；沿用 v1 的 4000/12000/12000。

---

## v1-reconstructed-2026-11（2026-11-02，刘思懿）· 历史版本

**背景**：当时以为 Zenodo 不可达（见 `docs/paper-deviations.md` DEV-01 历史），
按论文 §IV-B 的标注准则重建了 Stage-1 / Stage-2 两份模板。

**Stage-1（`prompts/stage1.md`）**

- 输入：评论原文、`source` / `granularity` / `action_name` / `trigger` / `repo`、评论针对的改动（`review_diff`）。
- 三档定义：
  - `None`：纯表扬、寒暄、社交性内容，没有问题或建议；
  - `General`：有改进方向但过于笼统，提不出可执行的具体动作；
  - `Valid`：至少一个具体、可执行的问题或建议（点名了函数/变量/具体行为）。
- 判定步骤：先剔除社交内容 → 再判断是否指向代码 → 再判断是否足够具体 → 抽取 issue 清单。
- 输出契约：`{"label": "None|General|Valid", "issues": ["..."], "rationale": "..."}`。
- 边界样例（写进 prompt 的 few-shot 说明里）：`LGTM, thanks!` → `None`；
  `Please improve the readability here.` → `General`；
  `` `parse_config` should validate the extension. `` → `Valid`。

**Stage-2（`prompts/stage2.md`）**

- 输入：评论原文、Stage-1 的问题清单、评论针对的改动、**评论之后的文件修改**（`subsequent_changes`）。
- 四档定义：`Valid-Uncertain` / `Valid-Unaddressed` / `Valid-Partially` / `Valid-Fully`。
- 核心判定规则：**"解决"指后续修改实现了评论要求的行为，而不是恰好改动到相邻代码行**；
  文件被删除、改动过大或缺少后续修改时判 `Valid-Uncertain`。
- 逐条比对 issue 清单，输出 `addressed_items` / `unaddressed_items`，再由条数比例决定档位。
- 输出契约：`{"label": "...", "addressed_items": ["..."], "unaddressed_items": ["..."], "rationale": "..."}`。

**已知差异 / 待办**

1. 原文的 few-shot 数量与措辞未知；当前为少量说明性样例。
2. 未包含论文可能使用的"评论长度/上下文截断"细则；本模块统一按
   `MAX_COMMENT_CHARS=4000`、`MAX_DIFF_CHARS=12000`、`MAX_SUBSEQUENT_CHARS=12000` 截断（保留首 60% + 尾 40%）。
3. 拿到原始 prompt 后：新建 `v2-from-paper-appendix`，在同一 gold 子集上对比两版标签一致率与 OA/Macro-F1，
   把结论写回 `docs/paper-deviations.md` 的 DEV-01。
