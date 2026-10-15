# MACAU UNIVERSITY OF SCIENCE AND TECHNOLOGY
## School of Computer Science and Engineering
## Faculty of Innovation Engineering
### <<Software Project for Course Software Engineering>>

| | |
|---|---|
| **Homework ID** | Task2-User Requirements Specifications |
| **Report Title** | User Requirements Specifications for Reproducing an LLM-assisted Empirical Analysis Framework for AI-based Code Review Comments |
| **Student Name** | 尹捷睿 (Yin Jierui) / 杨弋驰 (Yang Yichi) / 刘思懿 (Liu Siyi) |
| **Student No.** | 1240014154 / 1240019521 / 1240021954 |
| **Date** | 2026.10.15 |

---

## Amendment History

| Version | Date | Modified By | Reviewed By | Amendment Details |
|---|---|---|---|---|
| 1.0 | 2026.10.15 | Group 8 | Group 8 | Initial version |

---

## Table of Contents

1. Introduction
   1.1 Purpose
   1.2 Notation
   1.3 Scope
   1.4 Context Diagram
   1.5 Definitions and Acronyms
   1.6 References
   1.7 Overview
2. General Description
   2.1 System Functions
   2.2 User Characteristics
3. General Constraints
   3.1 Software Constraints
   3.2 Hardware Constraints
4. Assumptions and Dependencies
5. Functional Requirements Master List
6. Functional Requirements Detail
   6.1 Data Loading and Validation (REQ-1.1)
   6.2 Configuration Management (REQ-1.2)
   6.3 Stage-1 Comment Classification (REQ-1.3, REQ-1.4)
   6.4 Stage-2 Adoption Judgement (REQ-1.5)
   6.5 Prompt and LLM API Management (REQ-1.6, REQ-1.7)
   6.6 Output and Evaluation (REQ-1.8, REQ-1.9, REQ-1.10)
   6.7 Machine-Learning Interpretability (REQ-1.11, REQ-1.12)
   6.8 Orchestration, Logging and Error Handling (REQ-1.13 – REQ-1.15)
   6.9 Optional Enhancements (REQ-1.16, REQ-1.17)
7. External Interface Requirement
   7.1 Data Interfaces
   7.2 User Interfaces
   7.3 Other Interfaces
8. Non-Functional Requirements
   8.1 System Performance
   8.2 Information Security
   8.3 Availability
   8.4 Capacity
9. Domain Requirements
10. Appendix: Requirement Prioritisation Summary

---

## 1. Introduction

### 1.1 Purpose

This document specifies the user requirements for reproducing an **LLM-assisted Empirical Analysis Framework for AI-based Code Review Comments**. The framework reconstructs the two-stage LLM annotation pipeline and the Random Forest + SHAP interpretable analysis described in the TSE 2026 paper *"Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions"*.

The requirements in this document have been elicited from three sources, in accordance with the task description:

1. **Assigned customer (compulsory)** — the peer project team assigned to Group 8 via the online team table. This source is represented by the completed questionnaire (`Task2-User-Requirements-Questionnaire-Group-8`).
2. **Real potential customers/users (optional)** — empirical software engineering researchers and student researchers who would reuse the reproduced framework.
3. **Internal team members (optional)** — Group 8 members as customers and users of their own system.

This document builds on the Task-1 Project Proposal and will be used to guide the High-Level Design (HLD) and subsequent implementation. Any change to the proposal or design arising from this specification must be reflected back into those documents.

### 1.2 Notation

This specification and its supporting documents and diagrams use **Unified Modelling Language (UML)** notation.

In addition, individual requirements are prioritised using the **MoSCoW** classification agreed with the assigned customer in the questionnaire:

| Notation | Meaning |
|---|---|
| **Must-have (M)** | Mandatory; the function must be implemented. |
| **Should-have (S)** | High priority; implement if time permits. |
| **Could-have (C)** | Low-priority optional feature. |
| **Won't-have (W)** | Will not be implemented in the current project scope. |

Requirement identifiers use the forms `REQ-1.x` (functional), `PERF-x.x`, `SEC-x.x`, `AVA-x.x`, `CAP-x.x` (non-functional), and `DOM-x.x` (domain).

### 1.3 Scope

The scope of the system is a **command-line research tool** that, given the public Zenodo datasets and a configuration file, runs an end-to-end pipeline that:

1. Loads and validates the AI code-review comment datasets and aligns them with the 150-sample gold-standard human annotations.
2. Executes Stage-1 classification (None / General / Valid) and extracts actionable issue checklists for Valid comments.
3. Executes Stage-2 adoption judgement (Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed) using code diff/hunk context.
4. Computes evaluation metrics (Overall Accuracy, Macro-F1, Precision/Recall, binary classification) and compares them against the paper-reported values.
5. Trains a stratified 5-fold Random Forest model on engineered features and produces SHAP visualisations (beeswarm and summary plots).
6. Emits annotated CSV outputs, evaluation tables, SHAP figures, and a log of run details, warnings and deviations.

The system does **not** perform any new data collection, and does **not** provide a graphical user interface.

### 1.4 Context Diagram

The system operates as a batch pipeline driven by a single entry script, interacting with three external entities: the public Zenodo datasets, the OpenAI-compatible LLM API, and the human operator (researcher). The diagram below shows how the system scope integrates with these related systems.

```
                    +------------------------------------------+
                    |        LLM-assisted Analysis System      |
                    |                                          |
+-----------+       |  +----------+   +----------+   +-------+ |
|  Zenodo   |------>|  |  Data    |-->| Stage-1  |-->|Stage-2| |
| Datasets  |  CSV  |  |  Loader  |   | Classify |   |Judge  | |
+-----------+       |  +----------+   +----------+   +-------+ |
                    |       |               |             |    |
+-----------+       |       |        +------+------+      |    |
|  LLM API  |<----->|       +------->|  Evaluation |<-----+    |
| (OpenAI)  |  REST |                | RF + SHAP   |           |
+-----------+       |                +-------------+           |
                    |                     |                    |
                    |                     v                    |
+-----------+       |          +--------------------+          |
| Operator  |<------|----------| CSV / Tables /     |          |
|(Researcher)|  YAML |          | SHAP figs / Logs   |          |
+-----------+  config|         +--------------------+          |
                    +------------------------------------------+
```

- **Zenodo datasets** provide the raw review comments, code diff/hunk context, and the 150 gold-standard labels.
- **LLM API** provides the classification and adoption-judgement inference.
- **Operator** supplies the YAML/JSON configuration and consumes the produced artefacts.

### 1.5 Definitions and Acronyms

| Term / Acronym | Definition |
|---|---|
| **LLM** | Large Language Model — used for the two-stage annotation pipeline. |
| **Stage-1** | First annotation stage: classifies a review comment as *None*, *General*, or *Valid*. |
| **Stage-2** | Second annotation stage: judges adoption status of Valid comments as *Uncertain*, *Unaddressed*, *Partially-Addressed*, or *Fully-Addressed*. |
| **RF** | Random Forest — the interpretable machine-learning model used for feature-effect analysis. |
| **SHAP** | SHapley Additive exPlanations — used for global feature-importance and directional-effect analysis. |
| **Gold-standard** | The 150-sample human-annotated dataset used as ground truth for evaluation. |
| **OA / Macro-F1 / P / R** | Overall Accuracy, Macro-averaged F1, Precision, and Recall evaluation metrics. |
| **Zenodo** | Public open-science repository hosting the paper's two appendix datasets. |
| **CSV** | Comma-Separated Values — the primary data exchange format. |
| **YAML / JSON** | Human-readable configuration file formats. |
| **API** | Application Programming Interface — the OpenAI-compatible LLM service. |
| **TSE** | IEEE Transactions on Software Engineering — the venue of the target paper. |

### 1.6 References

1. K. Sun, H. Kuang, S. Baltes, X. Zhou, H. Zhang, X. Ma, G. Rong, D. Shao, C. Treude, *"Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions,"* IEEE Transactions on Software Engineering, 2026. DOI: 10.1109/TSE.2026.3688237.
2. K. Sun et al., *"Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions,"* arXiv preprint arXiv:2508.18771, 2026.
3. K. Sun et al., *"Online Appendix 1,"* Zenodo. DOI: 10.5281/zenodo.19562449.
4. K. Sun et al., *"Online Appendix 2,"* Zenodo. DOI: 10.5281/zenodo.19562450.
5. Task1-Project Proposal-Final-For Group-8, 2026.09.25.
6. Task2-User Requirements Specifications Description, 2026.09.29.
7. F. Pedregosa et al., *"Scikit-learn: Machine Learning in Python,"* JMLR, vol. 12, pp. 2825–2830, 2011.
8. S. M. Lundberg and S.-I. Lee, *"A Unified Approach to Interpreting Model Predictions,"* NeurIPS, 2017.

### 1.7 Overview

Section 2 gives a general description of the system functions and the intended user types. Section 3 lists the general software and hardware constraints. Section 4 records the assumptions and dependencies. Section 5 is the functional requirements master list, detailed in Section 6. Section 7 describes the external interfaces. Section 8 specifies the non-functional requirements, and Section 9 the domain-specific requirements introduced by the paper-reproduction nature of the project.

---

## 2. General Description

### 2.1 System Functions

The high-level purpose of the system is to provide a reusable, end-to-end measurement pipeline for the target paper's empirical analysis. Its principal functions are:

1. **Data acquisition and validation** — download/load the two Zenodo appendix datasets, validate their fields, clean the data, and align entries with the 150 gold-standard labels.
2. **Two-stage LLM annotation** — classify comments (Stage-1) and judge adoption status (Stage-2) using the original prompt templates (with logged adjustments) and an OpenAI-compatible API.
3. **Evaluation** — compute classification and binary-adoption metrics on the gold-standard subset and compare them against the paper-reported values.
4. **Interpretable machine-learning analysis** — engineer features, train a stratified 5-fold Random Forest, and run SHAP to derive feature importance and directional effects.
5. **Artefact generation** — emit annotated CSVs, evaluation tables, SHAP figures, and run logs.
6. **Orchestration** — expose a single entry script (`run.py`) driven by a YAML/JSON configuration file.

### 2.2 User Characteristics

The system is used as a self-service command-line tool. The intended user types (roles) and their characteristics are:

| User Type | Characteristics | Interface required |
|---|---|---|
| **Assigned customer (peer project team)** | Non-expert in this specific framework; uses the tool to verify the reproduction is faithful. Expects one-command execution and clear, readable outputs. | Command-line entry script + configuration file. |
| **Empirical software engineering researcher** | Domain expert; may reuse the pipeline for related code-review studies. Expects reproducibility, documented deviations, and configurable parameters. | Command-line + YAML/JSON configuration. |
| **Student researcher (code-review study)** | Familiar with Python and ML basics; evaluates the reproduction for learning or follow-up work. | Command-line + user manual. |
| **Internal team members** | Implementers and maintainers; responsible for modules and integration. | Command-line + source-level documentation and unit tests. |

All users are technical users running the tool on desktop/laptop platforms (Windows / macOS / Linux) with Python 3.8+. No web browser or mobile platform is required.

---

## 3. General Constraints

### 3.1 Software Constraints

| ID | Constraint |
|---|---|
| SWC-1 | The system shall be implemented in **Python 3.8+**. |
| SWC-2 | Dependencies are limited to open-source libraries: **pandas, scikit-learn, shap, openai, difflib** (and standard library). |
| SWC-3 | The LLM models shall follow the original paper: **GPT-4.1** for Stage-1 and **o3-mini** for Stage-2, with **temperature = 0**. Where a model is deprecated/renamed, an equivalent alternative shall be substituted and the change documented. |
| SWC-4 | No proprietary or licensed software may be a hard dependency; LLM access relies only on the OpenAI-compatible API. |
| SWC-5 | All configuration shall be externalised into a YAML/JSON file; no hard-coded parameters in source code. |

### 3.2 Hardware Constraints

| ID | Constraint |
|---|---|
| HWC-1 | No specialised hardware is required; the pipeline must run on a standard desktop/laptop. |
| HWC-2 | A stable internet connection is required for LLM API calls and dataset download. |
| HWC-3 | Because LLM inference is API-based, no GPU is required for the annotation stages; the RF/SHAP analysis runs on CPU over the (small) gold-standard subset. |

---

## 4. Assumptions and Dependencies

1. The two Zenodo appendix datasets (DOI 10.5281/zenodo.19562449 and 10.5281/zenodo.19562450) are publicly downloadable and contain review text paired with code diff/hunk, the 150 gold-standard annotations, the original prompt templates, and the feature definitions.
2. A valid OpenAI-compatible API key is available to the user and can be supplied via the configuration file.
3. Full metric evaluation runs only on the 150 gold-standard samples (not the 22,000+ full dataset), as accepted by the customer.
4. The Random Forest model and SHAP analysis are reproducible by fixing the random seed.
5. The end-to-end entry script is `run.py`, executed once with no manual intermediate steps (ideal) or with minimal manual steps (acceptable).
6. Any divergence from the paper is expected to be recorded, explained, and reported honestly.

---

## 5. Functional Requirements Master List

| Req. ID | Requirement Name | Requirement Description | Priority |
|---|---|---|---|
| REQ-1.1 | Data loading & validation | Load public Zenodo datasets; validate fields; clean data; align with the 150 gold-standard labels. | Must |
| REQ-1.2 | Configuration management | Support a YAML/JSON configuration file for dataset path, model, and parameters. | Must |
| REQ-1.3 | Stage-1 classification | Classify AI review comments into None / General / Valid. | Must |
| REQ-1.4 | Issue-checklist extraction | For Valid comments, extract actionable issue checklists. | Must |
| REQ-1.5 | Stage-2 adoption judgement | Judge adoption status (Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed) with code diff/hunk context. | Must |
| REQ-1.6 | Prompt template management | Reuse original prompts; allow slight adjustment; log all changes. | Must |
| REQ-1.7 | LLM API invocation | Automatic retry, token/cost logging, configurable model selection and temperature. | Must |
| REQ-1.8 | Annotated output | Produce annotated CSV with all classification and adoption labels. | Must |
| REQ-1.9 | Evaluation metrics | Compute OA, Macro-F1, Precision, Recall, and binary (Addressed vs non-Addressed) metrics. | Must |
| REQ-1.10 | Paper comparison | Compare computed metrics to paper values and record gaps/deviations. | Must |
| REQ-1.11 | Random Forest model | Build stratified 5-fold RF over engineered features. | Must |
| REQ-1.12 | SHAP analysis & visualisation | SHAP beeswarm/summary plots; check directional consistency with the paper's four conclusions. | Should |
| REQ-1.13 | One-click entry script | Single `run.py` executes the whole workflow without manual intermediate operations. | Should |
| REQ-1.14 | Run logging | Log running details, warnings, and deviations. | Must |
| REQ-1.15 | Error handling | Human-readable errors/warnings; stop with clear prompts on dataset-field inconsistency. | Must |
| REQ-1.16 | Sample limit & cost budget | Allow user to set a sample limit and API cost budget. | Could |
| REQ-1.17 | Response caching & resume | Cache successful API responses and resume interrupted runs. | Could |

---

## 6. Functional Requirements Detail

### 6.1 Data Loading and Validation (REQ-1.1) — **Must**

- **Description:** Load the two public Zenodo appendix datasets, validate their structure against the paper documentation, clean the data, and align entries with the 150 gold-standard human-annotated labels.
- **System Input:** Paths/DOIs to the two Zenodo datasets; the gold-standard label file; optional field-mapping from the configuration file.
- **Display:** Progress messages during load/validation; a summary of record counts after cleaning; warnings for mismatched or dropped rows.
- **System Processing:**
  1. Resolve dataset locations from the configuration file.
  2. Read the datasets (CSV or equivalent).
  3. Validate required fields (review text, code diff/hunk, trigger mode, tool type, addressing labels).
  4. Apply data-cleaning filters (e.g. drop empty/duplicate entries).
  5. Align entries against the 150 gold-standard ground-truth labels.
- **System Output:** A validated, cleaned, in-memory dataset and a normalised internal representation ready for Stage-1/Stage-2.
- **Constraints:** Must not perform new data collection; must be reproducible given the same dataset files.
- **Data Handling:** Handle CSV/Unicode text; preserve raw review text and code context; track row provenance for traceability.
- **Error Handling:** If dataset fields are inconsistent with the paper documentation, **stop execution and output a clear error prompt** (as required by the customer). Missing files raise a human-readable error.

### 6.2 Configuration Management (REQ-1.2) — **Must**

- **Description:** Externalise all runnable parameters into a single YAML/JSON configuration file.
- **System Input:** A YAML/JSON file.
- **Display:** Confirmation of the loaded configuration at startup.
- **System Processing:** Parse and validate configuration; apply defaults for temperature (0), model names, paths, and random seed.
- **System Output:** A validated configuration object consumed by all modules.
- **Constraints:** No hard-coded parameters in source code.
- **Data Handling:** Validate types and required keys; report unknown/missing keys.
- **Error Handling:** On invalid configuration, stop and report the offending key and expected type.

### 6.3 Stage-1 Comment Classification (REQ-1.3, REQ-1.4) — **Must**

- **Description:** Automatically classify each AI review comment into **None / General / Valid**, and for Valid comments extract an actionable issue checklist.
- **System Input:** Cleaned comment records and the Stage-1 prompt template.
- **Display:** Per-batch progress and per-record classification result.
- **System Processing:**
  1. Build prompt from the comment text and context.
  2. Call the LLM (default GPT-4.1, temperature = 0).
  3. Parse the classification label; for Valid comments, extract the actionable issue checklist.
- **System Output:** Stage-1 labels and checklists, persisted into the annotated output.
- **Constraints:** Must reuse the original paper prompts (with logged adjustments).
- **Data Handling:** Store labels as enumerated values; keep the checklist as structured text.
- **Error Handling:** On unparseable LLM output, retry (see REQ-1.7) then record a warning in the log.

### 6.4 Stage-2 Adoption Judgement (REQ-1.5) — **Must**

- **Description:** For comments judged Valid in Stage-1, judge adoption status into **Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed** using the original review code diff/hunk and subsequent file modifications.
- **System Input:** Valid comments with code diff/hunk context and subsequent modification information.
- **Display:** Per-record Stage-2 result.
- **System Processing:** Build Stage-2 prompt combining comment + diff/hunk context; call the LLM (default o3-mini); parse the adoption label.
- **System Output:** Stage-2 adoption labels, persisted into the annotated output.
- **Constraints:** Only Valid comments proceed to Stage-2.
- **Data Handling:** Enumerated adoption labels; retain the code context used for each judgement.
- **Error Handling:** Same retry/record policy as Stage-1.

### 6.5 Prompt and LLM API Management (REQ-1.6, REQ-1.7) — **Must**

- **Description:** Manage prompt templates and LLM API calls, including retry, cost logging, and model/temperature configuration.
- **System Input:** Prompt templates; LLM parameters from configuration.
- **Display:** Progress and per-request cost/token reporting.
- **System Processing:**
  - Reuse original prompts; allow slight adjustments, logging every change.
  - Automatic retry (with backoff) when an API request fails.
  - Record token consumption and estimated API cost.
  - Configurable model selection (GPT-4.1 / o3-mini or substitutes) and temperature (default 0).
- **System Output:** Annotated results; a cost/token summary in the log.
- **Constraints:** Model substitution must be documented.
- **Data Handling:** Persist token counts and cost estimates per run.
- **Error Handling:** On persistent API failure/timeout, log a human-readable error and abort gracefully with a summary of completed work.

### 6.6 Output and Evaluation (REQ-1.8, REQ-1.9, REQ-1.10) — **Must**

- **Description:** Produce annotated outputs, compute evaluation metrics, and compare them to the paper's reported values.
- **System Input:** All classification/adoption labels; the 150 gold-standard labels; paper-reported metric values.
- **Display:** Evaluation tables rendered on screen and saved to files.
- **System Processing:**
  1. Export an annotated CSV containing all classification and adoption labels.
  2. Compute OA, Macro-F1, Precision, Recall over the six classes, plus binary metrics (Addressed = {Fully, Partially} vs all others).
  3. Compare computed metrics against paper values and record gaps/deviations.
- **System Output:** Annotated CSV; quantitative evaluation tables; binary-evaluation results; a deviation report.
- **Constraints:** Full metric evaluation only on the 150 gold-standard samples.
- **Data Handling:** All numeric metrics in machine-readable CSV and human-readable tables.
- **Error Handling:** If gold-standard labels are missing/insufficient, stop with a clear error.

### 6.7 Machine-Learning Interpretability (REQ-1.11, REQ-1.12) — **Must / Should**

- **Description:** Build a stratified 5-fold Random Forest over engineered features (Must), and run SHAP analysis with beeswarm/summary plots and directional-consistency checks against the paper's four conclusions (Should).
- **System Input:** Engineered feature set (code-text fraction, code-snippet presence, comment length, trigger mode, review granularity, tool type, etc.) and adoption labels.
- **Display:** SHAP beeswarm and summary plots; feature-importance ranking.
- **System Processing:** Train stratified 5-fold RF with a fixed random seed; compute SHAP values; verify whether feature-direction effects match the four conclusions (concise comments, code snippets, manual trigger, hunk-level review improve adoption).
- **System Output:** RF model results; SHAP beeswarm and summary plots; a direction-consistency report.
- **Constraints:** Random seed fixed for reproducibility.
- **Data Handling:** Export feature-importance and SHAP values to files.
- **Error Handling:** If SHAP output deviates from the paper, record the deviation and root-cause notes in the log (do not crash).

### 6.8 Orchestration, Logging and Error Handling (REQ-1.13, REQ-1.14, REQ-1.15) — **Should / Must**

- **Description:** A single entry script `run.py` drives the whole workflow (Should); every run writes a log of details, warnings and deviations (Must); errors are human-readable (Must).
- **System Input:** The configuration file and, optionally, CLI overrides.
- **Display:** Clear progress messages and readable console output.
- **System Processing:** Sequentially invoke data loading → Stage-1 → Stage-2 → evaluation → RF/SHAP; write a structured log throughout.
- **System Output:** A log file recording running details, warnings, and deviations; all downstream artefacts.
- **Constraints:** The workflow must not require manual intermediate operations (ideal), though a small number of manual steps is acceptable.
- **Data Handling:** Structured, timestamped log entries.
- **Error Handling:** Human-readable error/warning logs; on missing dataset, LLM timeout, or SHAP deviation, log clearly rather than crash silently.

### 6.9 Optional Enhancements (REQ-1.16, REQ-1.17) — **Could**

- **Description:** (a) Allow a sample limit and an API cost budget to be set before running; (b) cache successful API responses and resume interrupted runs to avoid repeated costs.
- **System Input:** Optional configuration keys for sample limit and cost budget; a local cache store.
- **Display:** Budget/sample usage progress.
- **System Processing:** Enforce limits; store successful responses keyed by request; on resume, skip already-cached requests.
- **System Output:** Reduced-cost re-runs.
- **Constraints:** Implement only if time permits.
- **Data Handling:** A local response cache.
- **Error Handling:** On exceeding budget, stop gracefully with a summary.

---

## 7. External Interface Requirement

### 7.1 Data Interfaces

| Interface | Description |
|---|---|
| **Zenodo datasets** | Input CSV/dataset files (Appendices 1 and 2) containing review comments, code diff/hunk, and the 150 gold-standard labels. |
| **Configuration file** | YAML/JSON input specifying dataset paths, model names, temperature, and random seed. |
| **Annotated CSV** | Output file with all classification and adoption labels. |
| **Evaluation tables** | Output CSV/tables with OA, Macro-F1, Precision, Recall, and binary metrics. |
| **SHAP figures** | Output image files (beeswarm and summary plots). |
| **Log file** | Output text file with run details, warnings, and deviations. |

### 7.2 User Interfaces

The only user interface is a command-line entry script `run.py`. There is no graphical or web interface. Users provide parameters through the YAML/JSON configuration file (preferred) with optional command-line overrides. Output is written to files and echoed as readable console messages.

### 7.3 Other Interfaces

| Interface | Description |
|---|---|
| **OpenAI-compatible LLM API** | REST interface used by Stage-1 and Stage-2 for inference. Requires an API key and internet access. |

---

## 8. Non-Functional Requirements

### 8.1 System Performance

| Req. Id | Description | Target |
|---|---|---|
| PERF-1.1 | Loading and validating the datasets (appendices). | On the order of seconds to a few minutes; no interactive response-time requirement. |
| PERF-1.2 | A single LLM annotation request (Stage-1/Stage-2). | Tolerates API latency and retries; overall runtime bounded by the API budget. |
| PERF-1.3 | RF training and SHAP analysis over the 150-sample subset. | Completes in seconds on a standard CPU. |
| PERF-1.4 | End-to-end pipeline execution. | Acceptable to run in the background; full metric evaluation only on the gold-standard subset is accepted. |
| PERF-1.5 | Re-runs with response caching (REQ-1.17). | Noticeably lower API cost and runtime than a cold run. |

### 8.2 Information Security

| Req. Id | Description |
|---|---|
| SEC-1.1 | The API key shall not be hard-coded in source code and shall not be written to logs or output files. |
| SEC-1.2 | Secrets are supplied via the local configuration file or environment variables and shall not be transmitted over any insecure channel except the target LLM API. |
| SEC-1.3 | All data processed are public Zenodo datasets; no personal or sensitive data are collected or stored. |
| SEC-1.4 | Local cache files (if implemented) shall not persist raw API credentials. |

### 8.3 Availability

| Req. Id | Description |
|---|---|
| AVA-1.1 | The tool is a local batch program and has no continuous availability requirement; it is "available" whenever the environment and dependencies are correctly installed. |
| AVA-1.2 | The pipeline depends on the availability of the OpenAI-compatible API and the Zenodo datasets; outages in these external services are out of scope and shall be reported as clear errors. |
| AVA-1.3 | No planned downtime applies. Unplanned unavailability is limited to external-service outages and local environment failures. |

### 8.4 Capacity

| Req. Id | Description |
|---|---|
| CAP-1.1 | The system must be able to load and validate the full datasets (22,000+ review comments). |
| CAP-2.1 | The evaluation and ML analysis are only required to process the 150 gold-standard samples, as accepted by the customer. |
| CAP-3.1 | The system is a single-user research tool; no concurrent-user requirement applies. |

---

## 9. Domain Requirements

The following domain-specific requirements arise from the paper-reproduction nature of this project and were confirmed as important by the assigned customer.

| Req. Id | Description | Priority |
|---|---|---|
| DOM-1.1 | Reproduced experimental settings must stay as consistent with the original paper as possible. | Must |
| DOM-1.2 | All deviations from the original paper (prompts, models, datasets, settings) must be logged and explained. | Must |
| DOM-1.3 | Experiments must be repeatable by fixing the random seed for the machine-learning model. | Must |
| DOM-1.4 | If an original setting cannot be reproduced (e.g. a deprecated LLM model), replace it with an equivalent alternative and document all changes. | Must |
| DOM-1.5 | When LLM output is non-deterministic even at temperature = 0, the limitation must be explicitly recorded in the log/report (rather than silently aggregating). | Must |
| DOM-1.6 | Differences between reproduced results and the paper's reported results must be reported honestly. | Must |

---

## 10. Appendix: Requirement Prioritisation Summary

| Priority | Functional Requirements |
|---|---|
| **Must-have** | REQ-1.1 – REQ-1.11, REQ-1.14, REQ-1.15 |
| **Should-have** | REQ-1.12, REQ-1.13 |
| **Could-have** | REQ-1.16, REQ-1.17 |
| **Won't-have** | (none explicitly excluded by the customer) |
