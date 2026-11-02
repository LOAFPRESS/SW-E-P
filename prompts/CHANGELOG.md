# Prompt 变更日志

> 依据 DOM-1.2：任何 prompt 改动都要在这里留痕，并同步 `config/config.yaml` 的 `prompts.version`。
> 版本号会写进 `annotations.csv` 的 `prompt_version` 列，`summary.json` 的 `run_fingerprint`
> 还包含两个模板的 sha256 前缀，因此"哪一版 prompt 产出了哪批标签"是可追溯的。

## v1-reconstructed-2026-11（2026-11-02，刘思懿）

**背景**：论文的原始 prompt 发布在 Zenodo 在线附录，当前环境无法访问（见 `docs/paper-deviations.md` DEV-01），
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
