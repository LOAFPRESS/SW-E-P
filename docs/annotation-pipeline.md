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
| Stage-1 模型 GPT-4.1、Stage-2 模型 o3-mini，`temperature=0` | `config/config.yaml` 中 `llm.stage1_model` / `llm.stage2_model` / `llm.temperature`，全部可配置（REQ-1.2） |
| 六类评价：`None`、`General`、`Valid-Uncertain`、`Valid-Unaddressed`、`Valid-Partially`、`Valid-Fully` | `swep.schema.SIX_CLASS_LABELS`；`final_label_for()` 负责两阶段合并 |
| 二分类：`Valid-Partially` + `Valid-Fully` = Addressed | `swep.schema.ADDRESSED_LABELS`、`AnnotationRecord.is_addressed` |
| Stage-1 OA 94.5% / F1 90.8%；Stage-2 OA 91.8% / F1 88.5%；六类平均 OA 86.1% / F1 74.6%（Table VII） | `python run.py annotate --write-report` 会在 `summary.json` 的 `evaluation` 与 `run_report.md` 中给出同样的 OA/Macro-F1，便于逐项对照 |
| 150 条 gold（file-level 50 / hunk-level 50 / human 50） | 通过 `data.split` 过滤源；`describe_dataset()` 输出各源计数，防止混入错误子集 |

## 3. 架构

```
run.py                     唯一入口（REQ-1.13）
 └─ swep.cli               参数解析、退出码、产物落盘
     ├─ swep.config        YAML 加载 / 深合并默认值 / ${VAR} 展开 / 结构校验（REQ-1.2）
     ├─ swep.data.loader   多格式读取 + column_map 列名适配 + 字段校验（REQ-1.1/1.8）
     ├─ swep.prompts       prompt 模板渲染、上下文截断、版本指纹（DOM-1.2）
     ├─ swep.pipeline      两阶段编排、缓存、预算、重试、审计日志（REQ-1.7/1.16/1.17）
     │   ├─ swep.llm.mock    离线确定性假模型（无 key 也能跑通端到端）
     │   ├─ swep.llm.client  OpenAI 兼容客户端（真实调用，推理模型参数差异已处理）
     │   ├─ swep.llm.parsing 严格 JSON 解析 + 修复重问 + 标签归一
     │   └─ swep.llm.cache   sqlite 响应缓存（断点续跑）
     ├─ swep.metrics       标签分布、OA、Macro-F1、混淆矩阵（不依赖 sklearn）
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

模型偶尔会加 ```json 围栏、写解释性前缀，或漏掉 `issues`。`swep.llm.parsing` 的处理顺序：

1. 去掉 Markdown 代码围栏，用括号配平扫描出第一个完整的 JSON 对象（字符串内的括号/转义安全）；
2. `label` 走 `Stage1Label.coerce` / `Stage2Label.coerce` 归一（大小写、`Valid_Fully`、`not addressed` 等别名）；
3. 结构不一致的兜底：`Valid` 却没有 issue → 若 rationale 足够具体则提升为单条 issue，否则降级 `General`；
   非 `Valid` 却带 issue → 清空并告警；
4. 仍然失败 → 追加 assistant 回复 + 一条修复指令重问（`llm.max_parse_retries`，默认 2 次），
   审计日志里记为 `stage1-repair` / `stage2-repair`。

## 4. 配置

所有可调参数在 `config/config.yaml`，代码中没有硬编码的模型名/路径/价格（REQ-1.2）。
`config/config.openai.yaml` 是真实调用的小批量版本（`limit: 5`、独立输出目录）。

| 键 | 含义 | 默认 |
|----|------|------|
| `run.name` / `run.limit` / `run.seed` | 运行名、样本上限（REQ-1.16）、随机种子 | `gold150-mock` / `null` / `42` |
| `run.abort_on_record_error` | 单条失败是否中断整批 | `false` |
| `data.path` / `format` / `column_map` / `split` | 数据路径、格式（auto/jsonl/json/csv）、列名映射、子集过滤 | 合成样例 / `auto` / `{}` / `null` |
| `llm.provider` | `mock`（离线）或 `openai` | `mock` |
| `llm.base_url` / `api_key_env` | OpenAI 兼容网关；**key 只从环境变量读**（SEC-1.1/1.2） | `null` / `OPENAI_API_KEY` |
| `llm.stage1_model` / `stage2_model` / `temperature` | 两个阶段的模型与采样温度 | `gpt-4.1` / `o3-mini` / `0` |
| `llm.max_output_tokens` / `timeout_s` / `max_parse_retries` | 输出上限、超时、解析修复次数 | `1024` / `60` / `2` |
| `llm.retry.{max_attempts,base_delay_s,max_delay_s,jitter_s}` | 指数退避重试（REQ-1.7） | `5 / 2.0 / 60.0 / 0.5` |
| `llm.budget.max_usd` + `prices_per_1m_tokens` | 成本预算与价格表（`null` 关闭预算） | `5.0` |
| `llm.cache.{enabled,path}` | 响应缓存 / 断点续跑（REQ-1.17） | `true` / `artifacts/cache.sqlite3` |
| `prompts.{stage1,stage2,version}` | 模板路径与版本号（DOM-1.2，改动必须 bump） | `prompts/*.md` / `v1-reconstructed-2026-11` |
| `output.dir` 等 | 产物目录与文件名 | `artifacts/` |

相对路径一律以**配置文件所在目录的上一级**（即仓库根）为基准解析。

## 5. 使用方式

```powershell
# 0) 环境（Python 3.8+，仓库内虚拟环境）
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# 1) 只校验数据、不调用 LLM
.\.venv\Scripts\python.exe run.py validate-data -c config/config.yaml

# 2) 离线端到端（mock provider，无需 API key）
.\.venv\Scripts\python.exe run.py annotate -c config/config.yaml --write-report

# 3) 小批量真实调用（需要 OPENAI_API_KEY，先设 5 条上限）
$env:OPENAI_API_KEY = "sk-..."
.\.venv\Scripts\python.exe run.py annotate -c config/config.openai.yaml --write-report

# 4) 换数据集 / 只跑 human 子集 / 忽略缓存
.\.venv\Scripts\python.exe run.py annotate -c config/config.yaml --dataset data/raw/gold150.csv --no-cache

# 5) 稳定性实验：整批重复 5 次（对应论文 temperature=0 跑 5 次的协议，DEV-04）
.\.venv\Scripts\python.exe run.py annotate -c config/config.openai.yaml --repeat 5 --write-report
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

161 个用例，覆盖：schema/标签归一、配置合并与校验、三种数据格式与 column_map、prompt 渲染与截断、
JSON 解析与修复、价格/重试/缓存、流水线（缓存命中、预算停止、重试恢复、解析修复、单条失败隔离、
审计日志无密钥）、CLI 退出码与产物（含 `--repeat` 稳定性）、指标计算（含分来源与一致性）。

## 8. 已知限制与下一步

1. **prompt 为按论文准则重建**（原 prompt 在 Zenodo 在线附录中，当前网络无法访问），
   偏差登记见 `docs/paper-deviations.md` 的 DEV-01。拿到原 prompt 后应做 A/B 对比并 bump 版本号。
2. **尚无真实 API 跑通 150 条 gold 的准确率**：目前只有离线 mock 验证（DEV-02/DEV-03）。
   下一步：配置 key → `config/config.openai.yaml` 跑 5 条 → 逐步放大到 150 条 → 对齐 Table VII。
3. **分来源指标已实现但仅在小样例上验证**：`evaluation.per_source` 给出 file-level / hunk-level / human
   的 OA 与 Macro-F1（对应论文 83.6/78.1、89.2/83.4、85.6/62.4）；n 很小时只对出现过的类做平均
   （`observed_labels`），不能直接和论文数字对比（DEV-06）。
4. **5 次重复实验的工程支持已就绪**：`--repeat 5` 输出一致性（`stability.agreement_rate`）与逐次分布，
   但真实 API 的 5 次跑批尚未执行（DEV-04）。
5. 与组长的数据接口约定见 `docs/annotation-csv-schema.md`；若 Zenodo 列名不同，只改 `data.column_map`。
