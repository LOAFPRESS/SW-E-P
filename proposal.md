# Reproducing an LLM-assisted Empirical Analysis Framework for AI-based Code Review Comments

| Field | Value |
|-------|-------|
| Homework ID | Task1-Project Proposal |
| Group Number | 8 |
| Project Web-site | https://github.com/LOAFPRESS/SW-E-P |
| Student Name | 尹捷睿 / 杨弋驰 / 刘思懿 |
| Student No. | 1240014154 / 1240019521 / 1240021954 |
| Date | 2026.09.25 |

## Abstract

This report proposes to reproduce an LLM-assisted empirical analysis framework for AI-based code review comments, based on the top-tier TSE 2026 paper "Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions." The project reconstructs the paper's two-stage LLM annotation pipeline - classifying review comments (None/General/Valid) and judging their adoption status - together with an explainable machine-learning analysis using Random Forest and SHAP. It reuses the public Zenodo datasets and original prompt templates, requiring no new data collection, and produces annotated outputs, evaluation metrics, and SHAP visualizations end-to-end through a single entry script. The work is divided among three members covering (1) data and evaluation, (2) the LLM annotation pipeline, and (3) ML interpretability.

## 1. Introduction

### 1.1 Background and Problem Diagnosis

- AI code-review tools based on GitHub Actions now generate review comments at scale. The target study covers 16 such tools, 178 repositories, and more than 22,000 review comments.
- Manually assessing whether tens of thousands of AI-generated review comments are adopted incurs excessive cost and hinders large-scale empirical analysis.
- The paper's core contribution - a two-stage LLM classification pipeline - is hard for external researchers to reproduce.
- No reusable measurement pipeline exists for evaluating new AI code-review tools.

### 1.2 Proposed Treatment Overview

- Reproduce the paper's two-stage LLM annotation framework together with RF/SHAP explainable analysis.
- Reuse the public Zenodo datasets and the original paper prompts; no new data collection will be performed.

## 2. Reproduced Paper and Datasets

The target paper is a genuine published work in the top-tier software engineering journal TSE, with datasets publicly available on Zenodo.

### 2.1 Paper Information

- Title: Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions
- Authors: Kexin Sun, Hongyu Kuang, Sebastian Baltes, Xin Zhou, He Zhang, Xiaoxing Ma, Guoping Rong, Dong Shao, Christoph Treude
- Publication: IEEE Transactions on Software Engineering (TSE), 2026
- DOI: 10.1109/TSE.2026.3688237
- arXiv Preprint: 2508.18771 (v2, 2026-04)
- Research Scale: 16 GitHub Actions-based AI review tools; 178 repositories; 22,000+ review comments
- Methodology: Two-stage LLM-based annotation framework + explainable machine learning (Random Forest + SHAP)

### 2.2 Datasets

- Appendix 1: DOI 10.5281/zenodo.19562449
- Appendix 2: DOI 10.5281/zenodo.19562450
- Important Reminder: Download and validate both appendices as early as possible. Verify whether they contain review texts paired with code diff/hunk, the 150-entry gold-standard human annotations, original prompt templates, and feature definitions. Adjust project scope if actual fields deviate from initial assumptions.

## 3. Proposed Framework and Work Plan

### 3.1 Team Profile

- Yin Jierui (Team Leader) - Dataset & Evaluation: Python data processing, data cleaning, metric computation, unit testing, integration and progress coordination.
- Liu Siyi - LLM Annotation Pipeline: LLM API integration, prompt engineering, batch inference scripting, debugging.
- Yang Yichi - ML Interpretability: machine-learning model building, SHAP analysis, data visualization, report writing.
- Note: All three members participate in requirement reviews, code reviews, documentation and demo preparation. The list above indicates module owners only; cross-member assistance is encouraged.

### 3.2 Proposed Treatment

- Stage-1: Classify comments into three categories: None / General / Valid. For Valid comments, extract actionable issue checklists.
- Stage-2: For Valid comments, judge adoption status against original review code diffs and subsequent file modifications into four classes: Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed.
- Analysis Phase: Build feature subsets, train stratified 5-fold Random Forest models, and run SHAP to obtain feature importance and directional effects.

### 3.3 Functional Features

- Load and validate the review-comment datasets (review text, code diff/hunk, trigger mode, tool type, labels).
- Automatically classify each comment into None / General / Valid using Stage-1.
- Extract actionable issue checklists for Valid comments.
- Judge adoption status (Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed) using Stage-2.
- Export the annotated results as CSV with a predefined schema.
- Train a Random Forest model and report Overall Accuracy and Macro-F1.
- Generate SHAP feature-importance and directional-effect visualizations.
- Run the whole pipeline end-to-end with a single command (python run.py).

### 3.4 Success Metrics

- Pipeline Usability (Hard Constraint): Running python run.py produces annotated CSV outputs, evaluation tables and SHAP visualizations end-to-end with no manual intervention.
- Classification Metrics: Report Overall Accuracy (OA) and Macro-F1 across six classes (None / General / Uncertain / Unaddressed / Partially-Addressed / Fully-Addressed) on the 150 gold-standard samples; compare against paper-reported values and explain deviations. Also compute binary metrics with the binarized label Addressed = {Fully-Addressed, Partially-Addressed} versus all others.
- SHAP Direction Consistency: Top-ranked features must align directionally with the paper's four conclusions: more concise comments, presence of code snippets, manual triggering, and hunk-level reviews correlate with higher adoption probability.
- Code Quality: Unit tests shall cover three core modules: data loader, metric calculation, and prompt encapsulation.

### 3.5 Resource Requirements

- Datasets: Zenodo repositories 10.5281/zenodo.19562449 and 10.5281/zenodo.19562450 (download and validate first).
- LLM Models: Follow the original paper - GPT-4.1 for Stage-1 and o3-mini for Stage-2, with temperature = 0. If models are deprecated or renamed, substitute equivalent alternatives and record changes in the report.
- Python Dependencies: pandas, scikit-learn, shap, openai, difflib.

### 3.6 Risks & Mitigation

- Unstable LLM outputs -> Set temperature=0; run multiple inferences for aggregation. Note that temperature=0 does not guarantee deterministic outputs; report this limitation transparently.
- High API costs -> Evaluate full metrics only over the 150 gold-standard samples; perform rough token-cost estimation upfront.
- Large divergence between reproduced SHAP rankings and paper results -> Record deviations and investigate root causes including feature subsets, random seeds and dataset versions.
- Mismatch between dataset fields/prompts and documented assumptions -> Complete validation in Weeks 1-2; narrow scope as fallback (e.g., reproduce only Stage-1 or only binary classification).

### 3.7 Work Division

#### 3.7.1 Yin Jierui (Team Leader) - Data & Evaluation Module

- Download and validate both Zenodo appendices; catalogue fields including review text, code hunk/diff, trigger mode, tool type, and addressing labels.
- Perform data cleaning and filtering; align against the 150 gold-standard ground-truth labels.
- Implement metric functions: Overall Accuracy (OA), Macro-F1, per-class Precision/Recall, binary-classification OA.
- Write unit tests for data loader and metric-computation functions.
- Centralize configuration via YAML/JSON files; deliver final integration and the end-to-end entry script run.py.
- Organize weekly meetings; maintain progress tracking and risk registers.

#### 3.7.2 Liu Siyi - Two-Stage LLM Annotation Pipeline

- Reconstruct Stage-1 (None/General/Valid + actionable-issue extraction) and Stage-2 (four-level addressing judgment) prompts from dataset appendices.
- Implement batch-inference scripts: OpenAI API invocation, temperature=0, retry-with-backoff logic, token-usage and cost logging.
- Realize Stage-1 classification and actionable-issue extraction; implement Stage-2 addressing judgment combining code diff context.
- Export annotated CSV conforming to a predefined schema. If classification accuracy diverges substantially from paper values, iterate on prompts and log all modifications.

#### 3.7.3 Yang Yichi - RF + SHAP Interpretability Module

- Feature engineering: construct the paper-replicated feature set including code-text fraction, presence of code snippets, comment length, trigger mode, hunk-level versus file-level review granularity, tool type, etc.
- Train stratified 5-fold Random Forest and output OA / F1 scores.
- SHAP workflow: compute global feature importance and directional effects; produce beeswarm and summary plots.
- Validate SHAP directional outputs against the paper's four core conclusions; deliver visualizations and contribute analysis sections to the final report.

#### 3.7.4 Parallel-Execution & Dependency Notes

The workflow forms a serial chain: Yin Jierui (Data) -> Liu Siyi (Annotation) -> Yang Yichi (Analysis), where Liu Siyi's work constitutes the main bottleneck. To avoid integration failures in the final two weeks, Yang Yichi should build a skeleton RF+SHAP pipeline with placeholder/synthetic labels as early as Weeks 2-4.

### 3.8 Plan of Work and Product Ownership

#### 3.8.1 Short-Term Plan

- Weeks 1-2: Download and validate both Zenodo appendices; catalogue dataset fields; reconstruct Stage-1 and Stage-2 prompt templates.
- Weeks 3-4: Implement the two-stage LLM annotation pipeline; complete data cleaning and alignment to the 150 gold-standard labels; build a skeleton RF+SHAP pipeline with placeholder labels.
- Week 5: Integrate the end-to-end entry script run.py; wire configuration (YAML/JSON); add unit tests for the data loader, metric calculation, and prompt encapsulation.
- Week 6: Compute evaluation metrics, produce SHAP visualizations, compare against the paper conclusions, and draft the final report.

#### 3.8.2 Product Ownership (One Person per Group)

- Group A - Yin Jierui: Functionality - dataset collection and storage, data cleaning and alignment, metric computation, end-to-end integration (run.py). Qualitative property - the pipeline runs end-to-end without manual intervention and reproduces paper-level metrics on the 150 gold-standard samples.
- Group B - Liu Siyi: Functionality - two-stage LLM annotation (Stage-1 classification and actionable-issue extraction, Stage-2 adoption judgment), batch inference, CSV export. Qualitative property - annotation accuracy stays within a reasonable margin of the paper's reported values, with controlled API cost.
- Group C - Yang Yichi: Functionality - feature engineering, Random Forest training, SHAP interpretability analysis, visualization. Qualitative property - SHAP directional results are consistent with the paper's four core conclusions, with clear and interpretable plots.

## References

1. K. Sun, H. Kuang, S. Baltes, X. Zhou, H. Zhang, X. Ma, G. Rong, D. Shao, and C. Treude, "Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions," IEEE Transactions on Software Engineering, 2026. DOI: 10.1109/TSE.2026.3688237.
2. K. Sun et al., "Does AI Code Review Lead to Code Changes? A Case Study of GitHub Actions," arXiv preprint arXiv:2508.18771, 2026.
3. K. Sun et al., "Online Appendix 1," Zenodo. DOI: 10.5281/zenodo.19562449.
4. K. Sun et al., "Online Appendix 2," Zenodo. DOI: 10.5281/zenodo.19562450.
5. F. Pedregosa et al., "Scikit-learn: Machine Learning in Python," Journal of Machine Learning Research, vol. 12, pp. 2825-2830, 2011.
6. S. M. Lundberg and S.-I. Lee, "A Unified Approach to Interpreting Model Predictions," in Advances in Neural Information Processing Systems (NeurIPS), 2017.
