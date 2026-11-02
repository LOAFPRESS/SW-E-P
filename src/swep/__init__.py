"""SW-E-P: LLM-assisted annotation pipeline for AI code-review comments.

This package reproduces the two-stage LLM annotation framework described in
Sun et al., "Does AI Code Review Lead to Code Changes? A Case Study of GitHub
Actions", IEEE TSE 2026 (arXiv:2508.18771).

Module ownership (Group 8):
    * Member A (Yin Jierui)  - data loading / evaluation metrics / run.py integration
    * Member B (Liu Siyi)    - THIS PACKAGE: Stage-1 + Stage-2 annotation, LLM access,
                               prompt management, batch inference, annotated CSV export
    * Member C (Yang Yichi)  - feature engineering, Random Forest, SHAP

The code in this package is deliberately dependency-light (standard library +
``openai`` + ``pandas`` + ``PyYAML``) so that it can be integrated into the
``run.py`` end-to-end entry script owned by Member A.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
