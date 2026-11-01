"""Harte Ausstiege: Stop-Loss, Trailing-Stop, Take-Profit (01.11.2026).

ANLASS: Die Aktien-Depots (batch_trader) speicherten beim Kauf stop_loss
und take_profit, aber kein Code pruefte sie - engine.signal_aktion(), die
einzige Pruefstelle, wird nirgends aufgerufen. Verkauft wurde nur, wenn die
KI es entschied.

Trailing-Stop: Der Stop zieht mit dem Hoechstkurs seit Kauf nach und
behaelt dabei den Abstand der Risikostufe (risk_controller.params(risk)
["stop_loss"], z. B. 0.92 = 8 % unter dem Hoch). Er steigt nur, faellt nie.

settings.json (optional):
    "trailing_stop": {"aktiv": true}
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def trailing_aktiv():
    try:
        with open(os.path.join(BASE, "settings.json"), encoding="utf-8") as f:
            cfg = (json.load(f) or {}).get("trailing_stop") or {}
        return bool(cfg.get("aktiv", True))
    except Exception:
        return True


def stop_faktor(risk):
    try:
        from risk_controller import params
        return float(params(risk)["stop_loss"])
    except Exception:
        return 0.92


def nachziehen(stop, hoch, kurs, faktor, aktiv=True):
    """Neuer (stop, hoch). Ohne gueltigen Kurs bleibt alles unveraendert."""
    if not kurs or kurs <= 0:
        return stop, hoch
    hoch = max(float(hoch or 0), float(kurs))
    if aktiv and faktor and 0 < faktor < 1:
        kandidat = hoch * faktor
        if stop is None or kandidat > stop:
            stop = kandidat
    return stop, hoch


def pruefe_position(pos, kurs, risk, aktiv=None):
    """Aktualisiert pos (dict) in-place und gibt den Ausstiegsgrund zurueck:
    "stop_loss", "trailing_stop", "take_profit" oder None.

    pos braucht avg_price; stop_loss/take_profit/hoch_seit_kauf sind optional.
    """
    if not kurs or kurs <= 0:
        return None
    if aktiv is None:
        aktiv = trailing_aktiv()
    faktor = stop_faktor(risk)
    stop_alt = pos.get("stop_loss")
    if stop_alt is None and pos.get("avg_price"):
        stop_alt = pos["avg_price"] * faktor
    stop_neu, hoch = nachziehen(stop_alt, pos.get("hoch_seit_kauf") or pos.get("avg_price"),
                                kurs, faktor, aktiv)
    pos["hoch_seit_kauf"] = round(hoch, 6)
    if stop_neu is not None:
        pos["stop_loss"] = round(stop_neu, 6)
    if stop_neu is not None and kurs <= stop_neu:
        # Liegt der Stop ueber dem Einstand, war es der Trailing-Stop
        if pos.get("avg_price") and stop_neu > pos["avg_price"] * faktor * 1.0001:
            return "trailing_stop"
        return "stop_loss"
    tp = pos.get("take_profit")
    if tp and kurs >= tp:
        return "take_profit"
    return None
