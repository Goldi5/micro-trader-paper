#!/usr/bin/env python3
"""Test timeseries for all depots, find ones with most trades."""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import json, subprocess, glob, os

os.chdir(_MT_BASE)
files = sorted(glob.glob('depot*.json')) + ['depot.json']
results = []
for f in files:
    try:
        d = json.load(open(f))
        trades = d.get('trades', [])
        start = float(d.get('start_wert', d.get('start', 100)))
        if len(trades) >= 3:
            out = subprocess.check_output(['python3', 'timeseries.py', f]).decode()
            ts = json.loads(out)
            vals = [p['value'] for p in ts]
            results.append((f, len(trades), round(vals[0],2), round(vals[-1],2), len(ts)))
    except Exception as e:
        pass

results.sort(key=lambda x: -x[1])
for f, nt, first, last, pts in results[:8]:
    print(f'{f}: trades={nt}, points={pts}, first={first}, last={last}')
