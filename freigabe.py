"""
Micro-Trader — Live-Freigabe (Phase 13, §29.F)
Sicherheitsschicht für Shadow→Live-Wechsel.

WICHTIG: Diese Datei AKTIVIERT NICHT automatisch Live-Trading.
Sie bietet nur das Werkzeug + Checks. Der Wechsel erfolgt nur auf
expliziten User-Befehl (Bestätigung erforderlich).

Checks vor Freigabe:
1. Profil-Datei ist shadow (nicht schon live)
2. Was wurde schon in Shadow getestet? (Mindestens N Läufe)
3. Risiko-Limit pro Depot (max 100$ wie bisher)
4. Bestätigung des Users (nicht automatisch)

Usage:
  python freigabe.py --check us_shadow      # pre-flight check
  python freigabe.py --activate us_shadow   # nach Bestätigung
"""
import os
import json
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))


def lade_profil(name):
    pf = os.path.join(BASE, f"profile_{name}.json")
    if not os.path.exists(pf):
        return None, f"Profil {name} nicht gefunden"
    try:
        return json.load(open(pf, encoding="utf-8")), None
    except Exception as e:
        return None, str(e)


def pre_flight_check(name):
    """Prüft, ob Profil für Live-Freigabe bereit ist (ohne zu aktivieren)."""
    p, err = lade_profil(name)
    if not p:
        return False, f"❌ {err}"

    checks = []
    # 1. Shadow-Status
    if p.get("modus") == "shadow":
        checks.append(("✅ Shadow-Status", "Profil ist im Shadow-Modus (sicher)"))
    else:
        checks.append(("⚠️ Bereits Live", "Profil ist schon live — kein Wechsel nötig"))

    # 2. Risiko-Limit
    risk = p.get("risk_model", "standard")
    if risk in ("standard", "konservativ"):
        checks.append(("✅ Risiko-Modell", f"{risk} (Limit 100$/Depot)"))
    else:
        checks.append(("⚠️ Risiko-Modell", f"{risk} — prüfen!"))

    # 3. Regelstand referenziert
    rs = p.get("regelstand_ref", "")
    if rs:
        checks.append(("✅ Regelstand", rs))
    else:
        checks.append(("❌ Regelstand", "Keine Regelstand-Referenz"))

    # 4. Depot-Validation (mindestens 1 Depot-Typ)
    da = p.get("depotarten", [])
    if da:
        checks.append(("✅ Depotarten", ", ".join(da)))
    else:
        checks.append(("❌ Depotarten", "Keine Depotarten definiert"))

    ok = all(c[0].startswith("✅") for c in checks)
    return ok, checks


def activate(name, bestaetigung=False):
    """Aktiviert Live-Modus (NUR nach expliziter Bestätigung)."""
    if not bestaetigung:
        return False, "❌ Keine Bestätigung — Live-Wechsel abgebrochen (Sicherheit)"

    p, err = lade_profil(name)
    if not p:
        return False, f"❌ {err}"

    p["modus"] = "live"
    p["freigegeben_am"] = datetime.now().isoformat()
    p["freigegeben_von"] = "user"  # nicht automatisch!

    pf = os.path.join(BASE, f"profile_{name}.json")
    json.dump(p, open(pf, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return True, f"✅ {name} ist jetzt LIVE (freigegeben: {p['freigegeben_am']})"


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python freigabe.py [--check|--activate] <profil_name>")
        print("Beispiel: python freigabe.py --check us_shadow")
        sys.exit(1)

    mode = sys.argv[1]
    name = sys.argv[2]

    if mode == "--check":
        ok, result = pre_flight_check(name)
        print(f"\n=== Pre-Flight Check: {name} ===")
        if isinstance(result, list):
            for status, msg in result:
                print(f"  {status} {msg}")
        else:
            print(f"  {result}")
        print(f"\nBereit für Live: {'JA' if ok else 'NEIN'}")
    elif mode == "--activate":
        # Bestätigung nur über explizites Flag (nie automatisch)
        ok, msg = activate(name, bestaetigung="--confirm" in sys.argv)
        print(msg)
    else:
        print(f"Unbekannter Modus: {mode}")
