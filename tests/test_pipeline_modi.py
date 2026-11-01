"""Regressionstest: die Pipeline akzeptiert alle Modi, mit denen der
Scheduler sie startet (u. a. "ki_welle --welle N"). Offline, per AST/Parser."""
import ast
import os
import re
import sys

HIER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pl = open(os.path.join(HIER, "micro-trader-pipeline.py"), encoding="utf-8").read()
sch = open(os.path.join(HIER, "micro_trader_scheduler.py"), encoding="utf-8").read()

m = re.search(r'add_argument\("--mode", choices=(\[[^\]]*\])', pl)
erlaubt = set(ast.literal_eval(m.group(1))) if m else set()
gestartet = set(re.findall(r'start_pipeline\("([a-z_]+)"', sch))
fehlend = sorted(gestartet - erlaubt)
ok = bool(gestartet) and not fehlend and '"--welle"' in pl
print(("  OK    " if ok else "  FEHL  ") + "Scheduler-Modi %s erlaubt (fehlend: %s)" % (sorted(gestartet), fehlend))
print("ERGEBNIS: %d Fehler" % (0 if ok else 1))
sys.exit(0 if ok else 1)
