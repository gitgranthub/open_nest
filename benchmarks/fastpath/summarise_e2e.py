"""The tracked summary of a full end-to-end run: every metric and turn, no file contents.

    .venv/bin/python benchmarks/fastpath/summarise_e2e.py e2e.json [closure_summary.json]

Reads ``results/raw/<name>`` (written by bench_e2e.py, gitignored because it carries a copy
of every final project file) and writes ``results/e2e_summary.json``, which
``analyse_e2e.py`` reads to regenerate every table in SPIKES.md section 25G. The final
files are replaced by a SHA-256, which is all the analysis needs from them: whether two
arms ended identically.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RAW = RESULTS / "raw"

rows = json.loads((RAW / sys.argv[1]).read_text())
summary = []
for row in rows:
    kept = {k: v for k, v in row.items() if k not in ("files", "first_files")}
    kept["files_sha"] = hashlib.sha256(
        json.dumps(row["files"], sort_keys=True).encode()).hexdigest()
    summary.append(kept)
out = RESULTS / (sys.argv[2] if len(sys.argv) > 2 else "e2e_summary.json")
out.write_text(json.dumps(summary, indent=1) + "\n")
print(len(summary), "results ->", out)
