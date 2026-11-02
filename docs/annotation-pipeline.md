# 两阶段 LLM 标注流水线（模块设计说明）

> 负责人：刘思懿（1240021954）· 对应 Task2 URS 中 REQ-1.1 ~ REQ-1.17、SEC-1.1/1.2、DOM-1.2/1.4/1.5
> 论文：Sun et al., *Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions*, TSE 2026（arXiv:2508.18771）
> 状态：W3–W4 里程碑达成（流水线、prompt、批量推理、CSV 导出、离线验证全部可运行）

## 1. 目的与边界

本模块负责论文实证流程的**前两步**（论文 §IV-B、Table VII）：

1. **Stage-1（有效性判定）**：把一条 review comment 分为 `None` / `General` / `Valid`；
   若为 `Valid`，同时抽取**可执行的问题清单**（issue checklist），作为 Stage-2 的输入。
2. **Stage-2（采纳判定）**：只对 `Valid` 评论，结合"评论之后该文件的修改"判断
   `Valid-Uncertain` / `Valid-Unaddressed` / `Valid-Partially` / `Valid-Fully` 四档。

边界之外（由组员负责，本模块只约定接口）：

| 事项 | 负责人 | 接口 |
|------|--------|------|
| 数据集清洗、特征工程、分层 5 折随机森林、最终评估 | 尹捷睿（组长） | 读本模块导出的 `annotations.csv`（schema 见 `docs/annotation-csv-schema.md`） |
| SHAP 可解释性与可视化 | 杨弋驰 | 同上，外加 `summary.json` 中的标签分布 |

## 2. 与论文的对齐点

| 论文设置 | 本模块实现 |
|----------|-----------|
| Stage-1 模型 GPT-4.1、Stage-2 模型 o3-mini，`temperature=0` | `llm.stage1_model` / `llm.stage2_model` / `llm.temperature`，全部可配置（REQ-1.2）；`openai` / `deepseek` / `qwen` 三个 provider 走同一套代码（DEV-09） |
| prompt 原文在 Zenodo 在线附录 | 已逐字落盘：`prompts/stage1_v2_original.md`、`prompts/stage2_v2_original.md`，`prompts.format: text`，版本 `v2-paper-2026-11`（DEV-01）；`prompts/stage1.md`/`stage2.md` 是早期的 JSON 重建版，只用于 mock 离线演示 |
| 六类评价：`None`、`General`、`Valid-Uncertain`、`Valid-Unaddressed`、`Valid-Partially`、`Valid-Fully` | `swep.schema.SIX_CLASS_LABELS`；`final_label_for()` 负责两阶段合并 |
| 二分类：`Valid-Partially` + `Valid-Fully` = Addressed | `swep.schema.ADDRESSED_LABELS`、`AnnotationRecord.is_addressed` |
| Stage-1 OA 94.5% / F1 90.8%；Stage-2 OA 91.8% / F1 88.5%；六类平均 OA 86.1% / F1 74.6%（Table VII） | `python run.py annotate --write-report` 会在 `summary.json` 的 `evaluation` 与 `run_report.md` 中给出同样的 OA/Macro-F1，便于逐项对照 |
| 150 条 gold（file-level 50 / hunk-level 50 / human 50） | `scripts/build_gold_dataset.py` 内连接 Zenodo 的 `llm_analysis/input/sampled_*_review.csv` 与 `labeled/(resolved)sampled_*_review.csv`，产出 `data/gold150.jsonl` + `.provenance.json`（SHA-256、标签码统计，DEV-02/DEV-07）；`data.split` 可只跑单一来源 |
| 输出为 `Classification:` 纯文本（附录解析脚本如此假设） | `swep.llm.parsing.parse_stage1_text` / `parse_stage2_text` 复刻附录 `extract_suggestion.py` / `analyze_addressed_status.py` 的规则；同时保留 JSON 解析器 |

## 3. 架构

```
run.py                     唯一入口（REQ-1.13）
 └─ swep.cli               参数解析、退出码、产物落盘
     ├─ swep.config        YAML 加载 / 深合并默认值 / ${VAR} 展开 / 结构校验（REQ-1.2）
     ├─ swep.providers     provider 表：openai / deepseek / qwen 的 base_url 与 key 变量
     ├─ swep.data.loader   多格式读取 + column_map 列名适配 + 字段校验（REQ-1.1/1.8）
     ├─ swep.data.zenodo   Zenodo 附录 → 150 条 gold + provenance（scripts/build_gold_dataset.py）
     ├─ swep.prompts       prompt 模板渲染、上下文截断、版本指纹（DOM-1.2）
     ├─ swep.pipeline      两阶段编排、缓存、预算、重试、审计日志（REQ-1.7/1.16/1.17）
     │   ├─ swep.llm.mock    离线确定性假模型（无 key 也能跑通端到端）
     │   ├─ swep.llm.client  OpenAI 兼容客户端（openai/deepseek/qwen；推理模型参数差异已处理）
     │   ├─ swep.llm.parsing JSON 解析 + 附录文本格式解析 + 修复重问 + 标签归一
     │   └─ swep.llm.cache   sqlite 响应缓存（断点续跑）
     ├─ swep.metrics       标签分布、OA、Macro-F1、混淆矩阵、分来源指标（不依赖 sklearn）
     └─ swep.export        annotations.csv / summary.json / run_report.md
```

### 3.1 单条记录的处理流程

```
load_dataset → ReviewRecord.validate()
  │
  ├─ Stage-1: stage1_messages(record) → LLM → parse_stage1()
  │     label = None/General  → final_label = label，跳过 Stage-2
  │     label = Valid         → 带 issue 清单进入 Stage-2
  │
  ├─ Stage-2: stage2_messages(record, issues) → LLM → parse_stage2()
  │     final_label = Valid-{Uncertain|Unaddressed|Partially|Fully}
  │
  └─ AnnotationRecord → annotations.csv（21 列固定 schema）
```

关键约定：

- **Stage-2 只在 Stage-1 为 `Valid` 时调用**（论文设定；非 Valid 评论没有"采纳"可言）。
- `Valid` 但 Stage-2 空缺时，`final_label_for()` 记为 `Valid-Uncertain`，而不是空标签，
  防止下游聚合时静默丢行。
- 单条记录失败（解析失败、调用失败）**默认不中断整批**（REQ-1.15）：
  该行 `error` 列写入原因，`is_addressed=0`，其余记录继续。
- `BudgetExceeded` 与不可重试的 provider 错误会**停止整批**并返回非零退出码。

### 3.2 解析与修复

模型偶尔会加 Markdown 围栏、写解释性前缀，或漏掉条目。解析器由 `prompts.format` 决定：

**JSON 格式**（`prompts/stage1.md`、`stage2.md`，早期重建版）：

1. 去掉 Markdown 代码围栏，用括号配平扫描出第一个完整的 JSON 对象（字符串内的括号/转义安全）；
2. `label` 走 `Stage1Label.coerce` / `Stage2Label.coerce` 归一（大小写、`Valid_Fully`、`not addressed` 等别名）；
3. 结构不一致的兜底：`Valid` 却没有 issue → 若 rationale 足够具体则提升为单条 issue，否则降级 `General`；
   非 `Valid` 却带 issue → 清空并告警。

**文本格式**（`prompts/*_v2_original.md`，论文附录原文）：

1. 先尝试 JSON 解析兜底（部分模型会主动输出 JSON）；
2. Stage-1：定位 `Classification:`，在其后按附录口径匹配 `not contain any issues or suggestions` /
   `only contain general ...` / `contain valid ...`（含附录的短路语 `Not contain any items.`、
   `Not contain specific items.`），取**最早出现**的短语，避免 "not fully addressed" 这类复合句误判；
   问题清单取 `Issues or Suggestions:` 到 `Classification:` 之间的列表；
3. Stage-2：`Classification:` 之后按 `not enough information` < `not addressed` <
   `partly/partially addressed` < `fully addressed` 的最早出现位置定档；`addressed items:` /
   `unaddressed items:` 分节取条目（注意 `unaddressed items:` 内部含 `addressed items:`，切片做了前缀排除）；
   附录的 "No change happened; the comment remains unaddressed." 这类短路句直接判 `Valid-Unaddressed`；
4. 两种格式都失败 → 追加 assistant 回复 + 格式对应的修复指令重问（`llm.max_parse_retries`，默认 2 次），
   审计日志里记为 `stage1-repair` / `stage2-repair`；修复指令本身随 `prompts.format` 切换措辞。

## 4. 配置

所有可调参数在 `config/*.yaml`，代码中没有硬编码的模型名/路径/价格（REQ-1.2）。

仓库自带 5 份配置，直接换 `-c` 即可：

| 配置 | provider | 用途 |
|------|----------|------|
| `config/config.yaml` | `mock` | 默认演示：12 条合成样例 + JSON 重建版 prompt，离线可跑 |
| `config/config.gold150.yaml` | `mock` | **真实 150 条 gold** 的离线冒烟（`data/gold150.jsonl`），只验证管线能吞下真实数据 |
| `config/config.deepseek.yaml` | `deepseek` | 真实标注：`deepseek-chat` + `deepseek-reasoner`，论文原版 prompt（`format: text`） |
| `config/config.qwen.yaml` | `qwen` | 同上，换 DashScope：`qwen-plus` + `qwen-max` |
| `config/config.openai.yaml` | `openai` | 拿到 OpenAI key 时的对照实验（`limit: 5`） |

`swep.providers` 里的 provider 表（key 变量名固定，**key 只从环境变量读**，SEC-1.1/1.2）：

| provider | base_url | 环境变量 |
|----------|----------|----------|
| `mock` | — | —（不需要） |
| `openai` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| `deepseek` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `DASHSCOPE_API_KEY` |

| 键 | 含义 | 默认 |
|----|------|------|
| `run.name` / `run.limit` / `run.seed` | 运行名、样本上限（REQ-1.16）、随机种子 | `gold150-mock` / `null` / `42` |
| `run.abort_on_record_error` | 单条失败是否中断整批 | `false` |
| `data.path` / `format` / `column_map` / `split` | 数据路径、格式（auto/jsonl/json/csv）、列名映射、子集过滤 | 合成样例 / `auto` / `{}` / `null` |
| `llm.provider` | `mock` / `openai` / `deepseek` / `qwen` | `mock` |
| `llm.base_url` / `api_key_env` | 覆盖 provider 的端点与 key 变量；留空则用 provider 默认 | `null` / `null` |
| `llm.stage1_model` / `stage2_model` / `temperature` | 两个阶段的模型与采样温度 | `gpt-4.1` / `o3-mini` / `0` |
| `llm.max_output_tokens` / `timeout_s` / `max_parse_retries` | 输出上限、超时、解析修复次数 | `1024` / `60` / `2` |
| `llm.model_params` | 按模型名追加的参数（如 `o3-mini: {reasoning_effort: medium}`、`deepseek-reasoner: {reasoning_effort: low}`） | `{}` |
| `llm.retry.{max_attempts,base_delay_s,max_delay_s,jitter_s}` | 指数退避重试（REQ-1.7） | `5 / 2.0 / 60.0 / 0.5` |
| `llm.budget.max_usd` + `prices_per_1m_tokens` | 成本预算与价格表（`null` 关闭预算）；价格是 2025 快照，**用前核对**（DEV-05） | `5.0` |
| `llm.cache.{enabled,path}` | 响应缓存 / 断点续跑（REQ-1.17） | `true` / `artifacts/cache.sqlite3` |
| `prompts.{stage1,stage2,version,format}` | 模板路径、版本号、输出格式（`json`/`text`）（DOM-1.2，改动必须 bump） | `prompts/*.md` / `v1-reconstructed-2026-11` / `json` |
| `output.dir` 等 | 产物目录与文件名 | `artifacts/` |

相对路径一律以**配置文件所在目录的上一级**（即仓库根）为基准解析。
推理模型（`o1`/`o3`/`o4` 前缀，或 `model_params` 里带 `reasoning_effort` 的模型，如 `deepseek-reasoner`）
不发 `temperature`、改用 `max_completion_tokens`；若只返回 `reasoning_content` 也会取回内容，
两者都空则按可重试失败处理。

## 5. 使用方式

```powershell
# 0) 环境（Python 3.8+，仓库内虚拟环境）
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 1) 从本机 Zenodo 附录包重建 150 条 gold（已生成过可跳过）
.\.venv\Scripts\python.exe scripts\build_gold_dataset.py

# 2) 只校验数据、不调用 LLM
.\.venv\Scripts\python.exe run.py validate-data -c config/config.gold150.yaml

# 3) 离线端到端（mock provider，无需 API key）
.\.venv\Scripts\python.exe run.py annotate -c config/config.yaml --write-report
.\.venv\Scripts\python.exe run.py annotate -c config/config.gold150.yaml --no-cache --write-report

# 4) 真实调用（DeepSeek / Qwen，论文原版 prompt；先 --dry-run 看成本）
$env:DEEPSEEK_API_KEY = "sk-..."
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --dry-run
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --write-report

$env:DASHSCOPE_API_KEY = "sk-..."
.\.venv\Scripts\python.exe run.py annotate -c config/config.qwen.yaml --limit 10 --write-report

# 5) 换数据集 / 只跑 human 子集 / 忽略缓存
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --dataset data/raw/gold150.csv --no-cache

# 6) 稳定性实验：整批重复 5 次（对应论文 temperature=0 跑 5 次的协议，DEV-04）
.\.venv\Scripts\python.exe run.py annotate -c config/config.deepseek.yaml --repeat 5 --write-report
```

`python run.py -c config/config.yaml` 省略子命令时默认执行 `annotate`。

`--repeat N` 的语义：整批记录连续跑 N 次；**只要 N>1 就禁用响应缓存**，否则第二次开始会命中缓存、
一致性永远是 100%。CSV 取第 1 次的标注结果，N 次的分布与一致性写入 `summary.json` 的 `stability`
与 `run_report.md`；累计费用超过 `llm.budget.max_usd` 时提前停止并在日志中告警。

| 退出码 | 含义 |
|--------|------|
| 0 | 整批完成（个别记录失败会写入 CSV 的 `error` 列，仍返回 0） |
| 1 | 未预期错误 |
| 2 | 配置或数据错误（缺字段、文件不存在、无 API key 等） |
| 3 | 因成本预算停止 |
| 4 | provider 拒绝（鉴权失败、模型不存在等） |

## 6. 产物

`artifacts/`（可用 `--output-dir` 改）：

| 文件 | 内容 |
|------|------|
| `annotations.csv` | 标注结果，21 列固定 schema（见 `docs/annotation-csv-schema.md`，REQ-1.8） |
| `summary.json` | 运行统计：标签分布、stage1 分布、addressed rate、tokens/cost、对 gold 的 OA/Macro-F1、**分来源指标**、`--repeat>1` 时的 `stability`、prompt 指纹 |
| `run_report.md` | 同一份统计的 markdown 版，可直接贴周报（`--write-report`） |
| `requests.jsonl` | 每次 LLM 调用的审计日志：阶段、模型、token、费用、耗时、是否命中缓存（REQ-1.7） |
| `run.log` | 运行日志（INFO 级，含 prompt 指纹与配置摘要，**不含 key**） |
| `cache.sqlite3` | 响应缓存；删掉或 `--no-cache` 即可强制重新推理 |

`summary.json` 里的 `run_fingerprint` = `prompt version:stage1 digest:stage2 digest`，
同一 fingerprint + 同一配置即可复现同一批输出，用于 DOM-1.4 的可追溯性。

## 7. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

241 个用例，覆盖：schema/标签归一、配置合并与校验（含 provider 表、key 变量、`prompts.format`）、
三种数据格式与 column_map、Zenodo gold 构建器（URL 解析、标签码映射、脏值归一、provenance）、
prompt 渲染与截断（含附录原文内联方式与 `describe_code_change` 四分支）、JSON 解析与附录文本解析、
价格/重试/缓存、OpenAI 兼容客户端（请求参数、推理模型、`reasoning_content` 回退、参数修复、密钥脱敏）、
流水线（缓存命中、预算停止、重试恢复、解析修复、text 格式端到端、单条失败隔离、审计日志无密钥）、
CLI 退出码与产物（含 `--repeat` 稳定性）、指标计算（含分来源与一致性）。

## 8. 已知限制与下一步

1. **原文 prompt 已到位，仅 `describe_code_change` 与 system message 为重建**：Stage-2 的
   "Subsequent Code Changes:" 段落按附录语义复刻，措辞未公开（DEV-01）。下一步：拿到函数原文后替换并 bump 版本。
2. **真实模型跑批尚未执行**：本机没有 OpenAI key，DeepSeek/Qwen 配置已就绪（`config.deepseek.yaml` /
   `config.qwen.yaml`）。下一步：设 `DEEPSEEK_API_KEY` → `--dry-run` → `--limit 10` → 150 条 →
   对齐 Table VII（DEV-09 说明为何不能直接比较 86.1%/74.6%）。
3. **分来源指标已就绪**：`evaluation.per_source` 给出 file-level / hunk-level / human 的 OA 与 Macro-F1
   （对应论文 83.6/78.1、89.2/83.4、85.6/62.4）；n 很小时只对出现过的类做平均（`observed_labels`）。
   mock 在 150 条真实 gold 上的数值（0.220/0.178）只证明脏值处理，不是实验结果（DEV-03）。
4. **5 次重复实验的工程支持已就绪**：`--repeat 5` 输出一致性（`stability.agreement_rate`）与逐次分布，
   真实 API 的 5 次跑批尚未执行（DEV-04）。
5. **gold 二分类占比与论文 RQ3 描述的差异已澄清**：论文 25.1% 的分母是 RQ3 自己的 3879 条
   Valid 评论（我们复核为 973/3879 = 25.08%），不是 150 条分层抽样 gold（我们 71/150 = 47.3%）；
   见 DEV-10。标注六分类不受影响。
6. 与组长的数据接口约定见 `docs/annotation-csv-schema.md`；若换数据源，只改 `data.column_map`。
