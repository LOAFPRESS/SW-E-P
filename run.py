#!/usr/bin/env python
"""Single entry point for the SW-E-P reproduction (REQ-1.13).

For now this script exposes the LLM annotation stage only (Member B).  When the
data/evaluation and feature stages are integrated, this file stays the only
entry point and dispatches to the other modules.

Typical use::

    python run.py validate-data -c config/config.yaml
    python run.py annotate -c config/config.yaml --limit 5 --write-report
    python run.py annotate -c config/config.yaml --provider openai --dry-run

The script only manipulates ``sys.path`` so that the package under ``src/``
works without being installed.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from swep.cli import main  # noqa: E402  (path set above)

if __name__ == "__main__":
    sys.exit(main())
