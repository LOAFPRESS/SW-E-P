# 与论文的偏差登记（Deviation Log）

> 需求依据：DOM-1.2（记录所有与原论文的偏差）、DOM-1.4（过程可追溯）、DOM-1.5（复现结论需注明偏差）。
> 维护人：刘思懿（标注模块）。任何新增偏差请追加一条 `DEV-xx`，**不要覆盖历史条目**。

## 登记模板

```
DEV-xx | 类别（数据/方法/实现/环境） | 论文做法 → 本项目做法 | 原因 | 影响 | 缓解/下一步 | 状态
```

## 当前偏差清单

### DEV-01 · prompt 为重建版，非论文原文

- **类别**：方法
- **论文做法**：Stage-1/Stage-2 的 prompt 原文在论文的 Zenodo 在线附录中发布。
- **本项目做法**：按论文 §IV-B 的标注准则、标签定义、示例（praise → `None`，笼统建议 → `General`，
  点名具体代码 → `Valid`；"解决"指实现要求而非改动相邻行）重建 `prompts/stage1.md` 与 `prompts/stage2.md`，
  版本号 `v1-reconstructed-2026-11`。
- **原因**：2026-11-02 在本机网络环境下 `zenodo.org` 不可达（TCP 超时，`web_fetch` 与公共代理均失败），
  且工作区内没有任何 Zenodo 数据文件；arXiv 正文未给出 prompt 全文。
- **影响**：模型在边界样例上的行为可能与论文不同，直接影响 Stage-1/Stage-2 准确率（论文 Table VII：
  Stage-1 OA 94.5%/F1 90.8%，Stage-2 OA 91.8%/F1 88.5%）。属于**最显著偏差**，报告中必须注明。
- **缓解/下一步**：拿到附录后逐条 A/B；模板的 `$` 占位符与 JSON 输出契约已固定，替换文本不影响代码；
  每次改动 bump `prompts.version` 并在 `prompts/CHANGELOG.md` 记录差异。
- **状态**：未消除（后续若拿到原文，补充一条对比结论）。

### DEV-02 · 验证数据集为自建合成样例

- **类别**：数据
- **论文做法**：150 条人工标注 gold（file-level 50 / hunk-level 50 / human 50），来自 Zenodo。
- **本项目做法**：`data/samples/sample_comments.jsonl` 12 条**合成**记录（`synthetic: true`），
  覆盖三种来源与全部六类标签，用于验证管线而非评估准确率。
- **原因**：同 DEV-01，Zenodo 数据无法获取。
- **影响**：当前 `summary.json` 中 `accuracy 0.583 / macro-F1 0.407` 是"mock 模型 vs 合成标签"的结果，
  **不能**用于与论文对比。
- **缓解/下一步**：拿到真实 CSV 后用 `data.column_map` 适配列名（见 `data/README.md`），
  在 `config/config.openai.yaml` 中替换 `data.path`，先跑 5 条抽检再全量。
- **状态**：未消除。

### DEV-03 · 离线验证使用 mock provider

- **类别**：实现
- **论文做法**：真实调用 GPT-4.1 / o3-mini（`temperature=0`）。
- **本项目做法**：默认 `llm.provider: mock`，用关键词启发式 + 哈希分桶生成确定性的标签与 rationale，
  与真实客户端实现同一 `LLMClient` 接口。
- **原因**：开发环境没有 API key；需求要求"无 key 也能跑通整条流水线"。
- **影响**：mock 的准确率无统计意义；但它验证了缓存、重试、预算、解析修复、CSV 导出等工程路径。
- **缓解/下一步**：设置 `OPENAI_API_KEY` 后 `--provider openai` 即为真实调用；两种 provider 的产物 schema 完全一致。
- **状态**：未消除（模拟侧属设计选择，报告中单列）。

### DEV-04 · 单次推理，未做 5 次重复

- **类别**：方法
- **论文做法**：`temperature=0` 下每个模型重复运行 5 次（用于估计输出稳定性）。
- **本项目做法**：默认 1 次；`run.seed` 与响应缓存保证可复现。已实现 `run.py annotate --repeat N`
  （2026-11-02 更新）：N>1 时自动禁用缓存、累加费用并对每批计算 `stability.agreement_rate`
  与逐次标签分布，写入 `summary.json` 与 `run_report.md`。
- **原因**：控制 API 成本（REQ-1.16）与开发时间。
- **影响**：**工程侧已支持**，但真实 API 的 5 次跑批尚未执行（无 API key），因此仍无运行间一致性数字。
- **缓解/下一步**：拿到 key 后 `--repeat 5` 跑一次，报告 agreement rate。
- **状态**：工程侧已消除，实验侧待跑（2026-11-02）。

### DEV-05 · 价格表为手工维护的近似值

- **类别**：实现
- **论文做法**：未涉及。
- **本项目做法**：`llm.budget.prices_per_1m_tokens` 内置 gpt-4.1 `$2/$8`、o3-mini `$1.1/$4.4`（每百万 token）。
- **原因**：费用只用于预算拦截与报告，不参与科学结论。
- **影响**：若官方调价，`cost_usd` 会偏差；模型名未命中价格表时回退 `default_price`。
- **缓解/下一步**：调用前按官方价目表更新配置；预算拦截只看估算，不做财务结算。
- **状态**：已登记，可接受。

### DEV-06 · 分来源指标

- **类别**：评估
- **论文做法**：Table VII 按 file-level（83.6/78.1）、hunk-level（89.2/83.4）、human（85.6/62.4）分别报告。
- **本项目做法**（2026-11-02 更新）：`swep.metrics.per_source_report()` + `evaluate_against_gold(..., sources=)`
  已按 `source` 分组输出 OA / Macro-F1 / 二分类指标，写入 `summary.json` 的 `evaluation.per_source`
  与 `run_report.md` 的 "Per source" 表。n 很小的分组只对出现过的类做平均（`observed_labels`），
  避免无支撑类把分数压低。
- **原因**：分组指标对组长判断"哪个来源最难标"很关键，工程成本低，故提前到 W4 完成。
- **影响**：小样例上的数字（file 0.833/0.700、hunk 0.25/0.25、human 0.5/0.333，n=12 合成数据）
  只用于验证管线，不能与论文对比；真实数据齐备后即可逐行对照。
- **缓解/下一步**：真实 150 条 gold 跑通后，用同一份 CSV 重算并填入报告表格。
- **状态**：已消除（工程与展示），实验侧待真实数据（2026-11-02）。

### DEV-07 · 数据集列名未核验

- **类别**：数据
- **论文做法**：Zenodo 提供固定列名的 CSV。
- **本项目做法**：`swep.data.loader` 内置字段别名（`comment_body`、`code_diff`、`subsequent_changes` 等）
  与 `data.column_map` 适配层；未见到的列名报错时提示 `Available columns`。
- **原因**：无法下载原始 CSV（DEV-01）。
- **影响**：首次接入真实数据时可能需要补别名或写 `column_map`；不会静默错读。
- **缓解/下一步**：拿到 CSV 后先跑 `run.py validate-data`，按报错补齐映射并更新 `data/README.md`。
- **状态**：未验证。

### DEV-08 · 新增的工程约束（非论文内容）

- **类别**：实现
- **论文做法**：论文只描述方法与结果，未规定工程约束。
- **本项目做法**：`run.limit` 样本上限、`llm.budget.max_usd` 预算拦截、响应缓存/断点续跑、
  审计日志、`--dry-run` 成本预估、退出码约定。
- **原因**：Task2 URS 的 REQ-1.7/1.13/1.16/1.17 与 SEC-1.1/1.2 要求。
- **影响**：不改变标注方法；缓存命中时不会重复计费（`cached_calls > 0`、`cost_usd = 0`）。
- **状态**：设计内新增，报告中说明即可。

## 复现与追溯

- 每次运行的 `summary.json` 含 `run_fingerprint` = `prompt version + 两个模板的 sha256 前缀`（DOM-1.4）。
- `artifacts/run.log` 记录配置摘要（不含密钥）、prompt 指纹、数据集统计。
- 同一 fingerprint + 同一配置 + 同一缓存目录 → 输出可逐字节复现（mock provider 下已验证）。
