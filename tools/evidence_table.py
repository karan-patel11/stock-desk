#!/usr/bin/env python3
# Deprecated: use `stockdesk evidence-table ...`. This shim keeps `python tools/evidence_table.py ...` from older docs working.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))  # a repo checkout without pip install
from stockdesk.cli import main  # noqa: E402

sys.exit(main(["evidence-table", *sys.argv[1:]]))
