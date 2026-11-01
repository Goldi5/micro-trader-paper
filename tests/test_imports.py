"""Import-Smoke-Test: alle fuenf Trader-Module + risk_controller muessen
importierbar sein. Nur lokale Importe, KEIN Netzwerk (yfinance laeuft nicht).

HINWEIS: 'tabulate' ist im venv NICHT installiert – das ist ein VORBESTANDENER
Mangel (auch in Commit 8da05cd vorhanden, paper_trader.py:12) und NICHT durch
den Risk-Rebuild verursacht. Fuer diesen Test wird ein minimaler Stub
eingespiegelt, damit paper_trader importierbar wird und sein
Risikoverhalten geprueft werden kann. Am Produktivcode wird NICHTS geaendert.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import sys
import types

M = _MT_BASE
sys.path.insert(0, M)

if "tabulate" not in sys.modules:
    try:
        import tabulate  # noqa: F401
    except ImportError:
        _stub = types.ModuleType("tabulate")
        _stub.tabulate = lambda *a, **k: "(tabulate-Stub: tabulate fehlt im venv)"
        sys.modules["tabulate"] = _stub

FEHLER = []
for mod in ("risk_controller", "strategie", "risk_profile", "engine",
            "batch_trader", "spec_trader", "paper_trader", "etf_trader"):
    try:
        __import__(mod)
        print("OK    import %s" % mod)
    except Exception as e:
        FEHLER.append("%s: %s: %s" % (mod, type(e).__name__, e))
        print("FEHL  import %s -> %s: %s" % (mod, type(e).__name__, e))

sys.exit(1 if FEHLER else 0)
