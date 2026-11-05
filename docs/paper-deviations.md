# 与论文的偏差登记（Deviation Log）

> 需求依据：DOM-1.2（记录所有与原论文的偏差）、DOM-1.4（过程可追溯）、DOM-1.5（复现结论需注明偏差）。
> 维护人：刘思懿（标注模块）。任何新增偏差请追加一条 `DEV-xx`，**不要覆盖历史条目**。

## 登记模板

```
DEV-xx | 类别（数据/方法/实现/环境） | 论文做法 → 本项目做法 | 原因 | 影响 | 缓解/下一步 | 状态
```

## 当前偏差清单

### DEV-01 · prompt 原文已取得；仅 `describe_code_change` 措辞为重建

- **类别**：方法
- **论文做法**：Stage-1/Stage-2 的 prompt 原文在论文的 Zenodo 在线附录中发布。
- **本项目做法**（2026-11-02 更新）：
  - 用户已把 Zenodo 附录包下载到本机，原版 prompt 已**逐字**写入
    `prompts/stage1_v2_original.md`（源自 `llm_analysis/extract_suggestion_prompter_3.py`
    的 `task_description_for_indentify_suggestion_12`）与 `prompts/stage2_v2_original.md`
    （源自 `analyze_addressed_prompter_4.py` 的 `task_description_for_analyze_addressed_7`），
    版本号 `v2-paper-2026-11`，`prompts.format: text`（原版输出是 `Classification:` 纯文本，
    不是 JSON），解析器按附录 `extract_suggestion.py` / `analyze_addressed_status.py` 的规则实现。
  - 仓库内仍保留 `prompts/stage1.md` / `prompts/stage2.md`（JSON 契约、版本 `v1-reconstructed-2026-11`），
    用于 mock 离线演示与 SQLite 缓存；两套模板由 `prompts.format` 切换，互不影响。
  - **残余重建**：Stage-2 的 `Subsequent Code Changes:` 段落由 `swep.prompts.builder.describe_code_change()`
    生成，附录只公布了 `describe_code_change` 的调用点与四种语义（无改动 / 文件被删除 / 重命名 / 普通修改），
    未公布逐字措辞；我们按这四种语义复刻（`File_Deleted` → "was deleted after the review"）。
  - 系统提示词也非原文（附录只有 user 侧模板），当前为一句话角色设定。
- **原因**：附录未公开 `describe_code_change` 的函数体与 system message。
- **影响**：标签定义、判定步骤、输入内联方式（`json.dumps(..., ensure_ascii=False)`）、输出契约已与论文一致；
  只有一段描述性前缀与 system 角色句不同，预期影响远小于 DEV-01 旧版本，但仍需 A/B 才能定罪量差。
- **缓解/下一步**：拿到 `describe_code_change` 原文后替换函数并 bump 版本；先用同一批 20 条对比两种措辞的标签差异。
- **状态**：主要偏差已消除（2026-11-02），残余措辞待 A/B。

### DEV-02 · 验证数据集：150 条真实 gold 已可用；合成样例仅作离线冒烟

- **类别**：数据
- **论文做法**：150 条人工标注 gold（file-level 50 / hunk-level 50 / human 50），来自 Zenodo。
- **本项目做法**（2026-11-02 更新）：`scripts/build_gold_dataset.py` 从本机 Zenodo 目录
  （`AIReviewActionAnalysis(Zenodo)`）内连接 `llm_analysis/input/sampled_*_review.csv` 与
  `llm_analysis/labeled/(resolved)sampled_*_review.csv`，按 `Comment_URL` 对齐 50/50/50 共 150 条，
  标签码 `0/1/2,-1/2,0/2,1/2,2` 映射到六类，产出 `data/gold150.jsonl` + `.provenance.json`
  （含每个源文件的 SHA-256，DOM-1.4）。`data/samples/sample_comments.jsonl`（12 条合成）仍保留，
  仅用于无数据/无网络时的冒烟测试。
- **原因**：真实数据已到位，评估必须基于它。
- **影响**：`config/config.gold150.yaml` 上的 mock 结果（accuracy 0.220 / macro-F1 0.178）
  **不是**实验结果，只证明管线能处理真实数据（含 `File_Deleted`、`nan`、空 `New_path` 等脏值）。
- **缓解/下一步**：配置 DeepSeek/Qwen key 后跑 `config/config.deepseek.yaml` 或 `config/config.qwen.yaml`，
  与论文 Table VII 对照。
- **状态**：数据侧已消除；实验结果待真实模型跑批。


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
- **本项目做法**：`llm.budget.prices_per_1m_tokens` 内置 gpt-4.1 `$2/$8`、o3-mini `$1.1/$4.4`、
  o4-mini `$1.1/$4.4`、deepseek-flash `$0.30/$1.20`、deepseek-v4-pro `$1.32/$3.96`（均为 2026-11 官方
  峰值时价）、deepseek-chat `$0.28/$0.42`、deepseek-reasoner `$0.55/$2.19`（旧名，保留兼容）、
  qwen-plus `$0.11/$0.28`、qwen-max `$0.34/$1.37`（每百万 token）。
- **原因**：费用只用于预算拦截与报告，不参与科学结论；接口查询只能拿到摘要页，无法确认逐项单价，
  故不编造精度、只保留数量级。
- **影响**：若官方调价，`cost_usd` 会偏差；模型名未命中价格表时回退 `default_price`。
  **用前务必核对官方价目表**，报告里的美元数只作量级参考。
- **缓解/下一步**：真实跑批前更新配置；预算拦截只看估算，不做财务结算。
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

### DEV-07 · 数据集列名

- **类别**：数据
- **论文做法**：Zenodo 提供固定列名的 CSV。
- **本项目做法**（2026-11-02 更新）：附录包到手后**逐列核验**，实际列名为
  `source_action, Comment_URL, Comment_HTML_URL, Review_Start_Line, Review_End_Line,
  Original_Commit_id, Merge_Commit_id, Diff_path, New_path, Body, Diff_hunk,
  Change_Until_Merged` 加 4 个空列；标签文件列为 `source_action, Comment_URL, Final Result`。
  `src/swep/data/zenodo.py` 直接按这些列名构建 gold（同时保留 `loader` 的别名与 `column_map` 适配层，
  供他人用不同导出版本时使用）。
- **原因**：验证适配层是否真的对得上真实数据。
- **影响**：无静默错读：缺列、未知标签码、未匹配的 `Comment_URL` 都会报清晰错误或被统计进
  `provenance.json` 的 `unlabeled`。
- **状态**：已消除（2026-11-02）。

### DEV-08 · 新增的工程约束（非论文内容）

- **类别**：实现
- **论文做法**：论文只描述方法与结果，未规定工程约束。
- **本项目做法**：`run.limit` 样本上限、`llm.budget.max_usd` 预算拦截、响应缓存/断点续跑、
  审计日志、`--dry-run` 成本预估、退出码约定。
- **原因**：Task2 URS 的 REQ-1.7/1.13/1.16/1.17 与 SEC-1.1/1.2 要求。
- **影响**：不改变标注方法；缓存命中时不会重复计费（`cached_calls > 0`、`cost_usd = 0`）。
- **状态**：设计内新增，报告中说明即可。

### DEV-09 · 用 DeepSeek / Qwen 替代 GPT-4.1 + o3-mini

- **类别**：环境（可复现性）
- **论文做法**：Stage-1 GPT-4.1、Stage-2 o3-mini（temperature=0）；Table VII 还对比了
  deepseek-v3 / deepseek-r1（Stage-2 最高 95.4%）等模型。
- **本项目做法**：`swep.providers` 内置 `openai` / `deepseek` / `qwen` 三个 OpenAI 兼容端点，
  `config/config.deepseek.yaml`（2026-11 API 的 `deepseek-flash`；如需更强 Stage-2 可换
  `deepseek-v4-pro`）与 `config/config.qwen.yaml`（`qwen-plus` + `qwen-max`）使用与论文**同一套原版 prompt**。
  附录的 `call_llm/registry.py` 本身就把 deepseek-v3（`deepseek_native`）与 deepseek-r1 当作一等公民，
  所以这条路是论文作者走过的，不是我们临时发明。
- **原因**：中国大陆访问 OpenAI 困难；团队没有 OpenAI key。
- **影响一（模型不同）**：与 Table VII 的 86.1%/74.6% 不可直接比较；但同一 prompt + 同一解析器 + 同一
  gold 集，可以把"prompt 移植是否成功"与"模型差异"分开讨论。deepseek-v3 / r1 恰好是论文报告过的模型，
  因此结果仍可放进论文的模型对比表作为参照行。
- **影响二（temperature）**：DeepSeek 思考模式下 `temperature` 失效（官方文档明示"无实际效果"）。
  我们的配置是 Stage-1 关思考（`reasoning_effort: none`，`temperature=0` 仍生效、与论文一致），
  Stage-2 开思考（`reasoning_effort: high`，`temperature` 不发）。论文的 Stage-2 用 o3-mini 同样
  不接受 `temperature`，因此这一点与论文的 Stage-2 观测条件基本对齐。
- **缓解/下一步**：若日后拿到 OpenAI key，用 `config/config.openai.yaml` 跑同一批数据做对照；
  报告中明确写"标注模型：deepseek-flash（Stage-1 无思考 / Stage-2 思考）"。
- **状态**：设计内替代（2026-11-02 按 DeepSeek 2026-11 模型名更新），需在报告中单列。

### DEV-10 · gold 二分类占比与论文 RQ3 描述的差异（已查明：不是同一份总体）

- **类别**：数据（已澄清）
- **论文做法**：RQ3 描述 Addressed = 25.1%、Not Addressed = 74.9%；AI-only 子集 Addressed = 9.2%。
- **最初的困惑**：按附录 `Final Result` 码映射我们的 150 条 gold，Addressed（Partially + Fully）
  = 71/150 = 47.3%，与 25.1% 差了一倍。
- **查明结论（2026-11-02）**：25.1% 的分母**不是**那 150 条人工 gold，而是 RQ3 自己的建模总体——
  附录 `address_feature_matrix/shape_labels_and_feature_under_LLM.py` 只保留 LLM 判定为 Valid 的评论
  （`Resolution_Formated` 以 `2` 开头且不等于 `2,-1`），并把 `2,0→0`、`2,1→1`、`2,2→1` 二值化。
  实际文件 `labels/all_reviews_with_LLM_labels.csv` 共 **3879** 行：`Change_Label=1` 973 行、
  `0` 2906 行 → **25.08%**，与论文 25.1% 吻合。按 `Source == Human` 拆开后：
  human 889 行（Addressed 78.6%）、AI-only **2990** 行（Addressed **9.16%**），
  与论文的 2990 条 / 9.2% 完全对应。
- **对我们的影响**：
  - 150 条 gold 是**分层抽样**（两种来源各 50），不是 RQ3 的总体，47.3% 与 25.1% 并不矛盾；
    我们在 150 条上做六分类评估（RQ2）不受影响。
  - **RQ3 复现不必重建特征**：附录已给出论文用的输入
    `address_feature_matrix/_selected_reviews_with_features/reviews_contains_valid_by_LLM_lda_topics_selected.csv`
    （3879 行 × 33 列，含 6 个 LDA topic 概率）与标签 `labels/all_reviews_with_LLM_labels.csv`，
    即论文 RF 的同一份数据。杨弋驰可直接用这两份文件对齐 88.6% / 0.846（150 条 gold）与
    91.7% / 0.647（AI-only）两组结果。
  - 我们自己跑批产出的 3879 条 LLM 标签可以与附录这份标签做一致性对比，作为"prompt 移植是否成功"的量化证据。
- **状态**：已澄清（2026-11-02），无需向组长追问口径；改由组长决定 RQ3 是用附录现成标签还是用我们的重跑标签。

### DEV-11 · RQ3 特征表缺 10 列：36 个特征而非论文清单的 46 个

- **类别**：数据（特征可用性）
- **论文做法**：RQ3 的特征清单有 36 个特征，来自论文的特征工程脚本；附录提供了其中 33 列可直接取用的数值。
- **本项目做法**：直接用附录 `_selected_reviews_with_features/reviews_contains_valid_by_LLM_lda_topics_selected.csv`
  （3879 行 × 33 列）构建矩阵，**不做任何替代或插补**。以下 10 个论文特征在该表里不存在：
  `Code_Total_Length`、`Comment_Changes`、`Commit_Accumulated_Changed_File_Count`、
  `Commit_Accumulated_Total_Add_Line_Count`、`Commit_Accumulated_Total_Change_Line_Count`、
  `File_Change_Line_Count`、`Repo_Total_File_Number`、`Repo_Total_PR_Number`、
  `Thread_Companion_Count`、`Timeline_Index`。
  `swep.features.build_feature_matrix` 把它们记进 `missing["numeric"]`，并在
  `artifacts/rq3/*/rq3_report.md` 的 "Features that the input table does not provide" 段落原样列出。
- **原因**：这些列需要从 GitHub API 的仓库/PR/时间线元数据重新采集，附录未随数据集发布（属于论文的原始爬取产物）。
- **影响**：实际建模 36 个特征（repo 3 / modification 12 / textual 5 / action 10 / topic 6），
  与论文报告的"36 个特征"数量一致、组成可能略有出入；实测 accuracy 0.8876 / macro-F1 0.8484
  （论文 0.886 / 0.846），AI-only 0.9187 / 0.6553（论文 0.917 / 0.647），
  差距均在 0.2 pp / 0.008 以内，说明缺失的 10 列对模型贡献很小，但**不能声称逐特征完全一致**。
- **缓解/下一步**：若需要补齐，可从 `_data/` 的原始爬取数据重算其中若干列（如
  `Commit_Accumulated_*`），再重跑 `scripts/run_rq3.py` 做敏感性对比；当前结论不依赖这些列。
- **状态**：已记录（2026-11-05），随 W5 交付。

### DEV-12 · RQ3 用附录现成标签复现，尚未用我们重跑的标签做敏感性分析

- **类别**：方法
- **论文做法**：RQ3 的标签由论文作者调用 LLM 批量标注后二值化（`2,0→0`、`2,1→1`、`2,2→1`）。
- **本项目做法**：第一版直接使用附录 `labels/all_reviews_with_LLM_labels.csv`（3879 行），
  以验证"特征 + 建模协议"这条链路；我们自己的 3879 条重跑标签尚未产出（等 API key）。
- **原因**：拿不到 key 时优先打通 RQ3 全链路，避免整条线阻塞。
- **影响**：当前 88.76% / 84.84% 与 91.87% / 65.53% 复现的是论文的**建模协议**，
  不包含"我们重新标注后结果是否稳定"这一层证据。
- **缓解/下一步**：拿到 key 后跑同一份 3879 条，用 `scripts/run_rq3.py --labels <我们的 CSV>`
  重跑，比较两次标签的一致率与指标漂移；这是最有力的"prompt 移植正确性"量化证据。
- **状态**：待办（2026-11-05），阻塞于 API key。

## 复现与追溯

- 每次运行的 `summary.json` 含 `run_fingerprint` = `prompt version + 两个模板的 sha256 前缀`（DOM-1.4）。
- `artifacts/run.log` 记录配置摘要（不含密钥）、prompt 指纹、数据集统计。
- 同一 fingerprint + 同一配置 + 同一缓存目录 → 输出可逐字节复现（mock provider 下已验证）。
