#!/usr/bin/env python3
"""Entry point: python3 ia.py <init|status|step|finding|detect|baseline|cite-check|merge-check|hygiene|filter|publish|render|eval> ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ia.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
