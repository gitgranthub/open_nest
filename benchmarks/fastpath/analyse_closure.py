"""The closure pass's cross-project acceptance run, one line per conversation.

    .venv/bin/python benchmarks/fastpath/analyse_closure.py closure_summary.json

Reads the tracked summary (summarise_e2e.py) of ``bench_e2e.py --set closure --arm fast``.
Every verdict is the automatic, objective one in ``grade_closure``; None means only a
reader can say, and SPIKES.md section 25M says what the reader found.
"""
import json, sys
from collections import defaultdict
from pathlib import Path
HERE = Path(__file__).resolve().parent
rows = json.loads((HERE / "results" / sys.argv[1]).read_text())
by = defaultdict(list)
seconds, calls, tokens = [], 0, 0
print(f"{'id':4} {'kind':10} {'working':8} {'routes':34} {'s':>6} {'calls':>5} {'tok':>5}  first message")
for row in rows:
    turns = row["turns"]
    routes = "/".join(t["route"] for t in turns)
    detail = "; ".join(
        f"{(t['fastpath'] or {}).get('recipe') or (t['fastpath'] or {}).get('reason', '')}"
        + (f" [{(t['fastpath'] or {}).get('result')}]" if (t['fastpath'] or {}).get('result') else "")
        for t in turns)
    s = sum(t["seconds"] for t in turns); c = sum(t["provider_calls"] for t in turns)
    o = sum(t["output_tokens"] for t in turns)
    seconds += [t["seconds"] for t in turns]; calls += c; tokens += o
    print(f"{row['id']:4} {row['profile'][:10]:10} {str(row['grade'].get('working')):8} {routes:34} "
          f"{s:6.1f} {c:5} {o:5}  {row['messages'][0][:50]!r}")
    print(f"{'':24}{detail[:150]}")
    by[row["profile"]].append(row["grade"].get("working"))
print()
for profile, verdicts in by.items():
    print(f"  {profile:13} working {sum(v is True for v in verdicts)}/{len(verdicts)}"
          + (f"  (not graded: {sum(v is None for v in verdicts)})" if None in verdicts else ""))
seconds.sort()
print(f"  messages {len(seconds)}, median {seconds[len(seconds)//2]:.1f} s, "
      f"model calls {calls}, generated tokens {tokens}")
