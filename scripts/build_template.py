#!/usr/bin/env python3
# Deprecated: use `stockdesk template ...` (same arguments). This shim keeps `python scripts/build_template.py` working.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # a repo checkout without pip install
from stockdesk.cli import main  # noqa: E402

sys.exit(main(["template", *sys.argv[1:]]))
