"""Test der Rueckfall-Kette in ki_entscheider.

Die Kette ist nur dann etwas wert, wenn der Ausfallpfad wirklich
greift. Also nicht nur lesen, sondern jeden Ausfall erzwingen.

Geprueft wird:
  1. Jev antwortet normal -> Stufe jev
  2. Jev antwortet nicht (Timeout) -> Stufe allam
  3. Jev und Allam fallen aus -> Stufe keine, kaufen = False
  4. Jev liefert Müll (ausserhalb 0..1) -> Stufe allam
  5. Jev liefert unparsebar -> Stufe allam
  6. Ungueltige Kennzahlen (leer) -> keine Ausnahme nach aussen
  7. Ein Ausfall fuehrt NIE zu einem Kauf

Punkt 7 ist die sicherheitskritische Eigenschaft: ein KI-Ausfall darf
nie dazu fuehren, dass etwas gekauft wird.
"""
# 01.11.2026: Basisordner statt fest /opt/micro-trader - so laeuft der Test
# auch in einer Kopie (run_tests.sh) und fasst keine Live-Daten an.
_MT_BASE = __import__("os").environ.get("MT_BASE") or __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import sys
import time

sys.path.insert(0, _MT_BASE)
import ki_entscheider as ke  # noqa: E402

GUTE_ZAHLEN = {
    "ticker": "AAPL", "risikostufe": 55,
    "score": 22.0, "mindestscore": 20.6,
    "beta": 0.88, "volatilitaet_prozent": 14.9,
    "rendite_1j_prozent": 22.1,
    "abstand_52w_hoch_prozent": -3.1,
    "konzentration_prozent": 12.0,
    "rsi": 58.0, "volumen_faktor": 1.2,
}

bestanden = 0
gesamt = 0


def pruefe(label, bedingung, zusatz=""):
    global bestanden, gesamt
    gesamt += 1
    if bedingung:
        bestanden += 1
        print("  [ok]   %-46s %s" % (label, zusatz))
    else:
        print("  [FAIL] %-46s %s" % (label, zusatz))


print("=" * 74)
print("  Test der Rueckfall-Kette")
print("=" * 74)
print()

# --- 1) Normalfall
print("  1) Normalfall: Jev antwortet")
t0 = time.time()
e = ke.entscheide(GUTE_ZAHLEN)
dt = time.time() - t0
pruefe("Stufe ist jev", e["stufe"] == "jev", "stufe=%s" % e["stufe"])
pruefe("p ist eine Zahl 0..1", isinstance(e.get("p"), (int, float)),
       "p=%s" % e.get("p"))
pruefe("kaufen ist boolesch", isinstance(e.get("kaufen"), bool),
       "kaufen=%s" % e.get("kaufen"))
# 5s war der erste Aufruf (Kaltstart). Gemessen: Median 0,25s,
# max 0,33s ueber 10 Aufrufe. 3s laesst Kaltstart zu, haelt Ausreisser fest.
pruefe("Latenz unter 3s (Kaltstart erlaubt)", dt < 3.0, "%.2fs" % dt)
print()

# --- 2) Jev faellt aus (Timeout)
print("  2) Jev faellt aus -> Allam uebernimmt")
_orig_jev = ke.jev_entscheide


def kaputt_jev(*a, **k):
    raise TimeoutError("simuliert: Jev antwortet nicht")


ke.jev_entscheide = kaputt_jev
t0 = time.time()
e = ke.entscheide(GUTE_ZAHLEN)
dt = time.time() - t0
pruefe("Stufe ist allam", e["stufe"] == "allam", "stufe=%s" % e["stufe"])
pruefe("kein Absturz", True, "%.2fs" % dt)
pruefe("Grund nennt den Ausfall", "Jev" in (e.get("rueckfall_grund") or ""),
       str(e.get("rueckfall_grund"))[:50])
print()

# --- 3) Beide fallen aus
print("  3) Beide fallen aus -> NICHT kaufen")
_orig_allam = ke.allam_entscheide


def kaputt_allam(*a, **k):
    raise RuntimeError("simuliert: Allam antwortet nicht")


ke.allam_entscheide = kaputt_allam
e = ke.entscheide(GUTE_ZAHLEN)
pruefe("Stufe ist keine", e["stufe"] == "keine", "stufe=%s" % e["stufe"])
pruefe("kaufen ist False", e["kaufen"] is False, "kaufen=%s" % e["kaufen"])
pruefe("kein Absturz", True)
pruefe("beide Fehler protokolliert",
       bool(e.get("fehler_jev")) and bool(e.get("fehler_allam")))
print()

# --- 4) Jev liefert einen Wert ausserhalb 0..1
print("  4) Jev liefert Müll -> Allam uebernimmt")
ke.jev_entscheide = _orig_jev          # <- Original wiederherstellen
ke.allam_entscheide = _orig_allam


def boese_jev(*a, **k):
    return {"stufe": "jev", "p": 7.5, "kaufen": True,
            "grund": "unsinnig", "sekunden": 0.1, "kosten_usd": 0.0}


# Der Wert ausserhalb 0..1 muss in jev_entscheide selbst abgefangen werden.
# Wir simulieren deshalb direkt die kaputte Antwort.
_orig_urlopen = ke.urllib.request.urlopen


def boese_antwort(*a, **k):
    import json as _j
    return _FakeResp(_j.dumps({
        "answers": {"kauf": {"type": "noul", "noul": 7.5}},
        "usage": {"cost": 0.0, "input_tokens": 100},
        "model": "test",
    }).encode())


class _FakeResp:
    def __init__(self, daten):
        self._d = daten

    def read(self):
        return self._d


ke.urllib.request.urlopen = boese_antwort
try:
    ke.jev_entscheide(GUTE_ZAHLEN)
    gefangen = False
except ValueError as ex:
    gefangen = "0..1" in str(ex) or "ausserhalb" in str(ex)
pruefe("Wert ausserhalb 0..1 wird abgewiesen", gefangen)
ke.urllib.request.urlopen = _orig_urlopen
print()

# --- 5) Jev liefert unparsebar
print("  5) Jev liefert unparsebar -> Allam uebernimmt")


def muell_antwort(*a, **k):
    return _FakeResp(b'{"answers": {"kauf": {"nicht": "da"}}}')


ke.urllib.request.urlopen = muell_antwort
try:
    e = ke.entscheide(GUTE_ZAHLEN)
    pruefe("Stufe ist allam", e["stufe"] == "allam", "stufe=%s" % e["stufe"])
except Exception as ex:
    pruefe("Stufe ist allam", False, "Ausnahme: %s" % str(ex)[:50])
ke.urllib.request.urlopen = _orig_urlopen
print()

# --- 6) Leere Kennzahlen
print("  6) Leere Kennzahlen -> keine Ausnahme nach aussen")
try:
    e = ke.entscheide({})
    pruefe("kein Absturz", True, "stufe=%s kaufen=%s" % (e["stufe"], e["kaufen"]))
except Exception as ex:
    pruefe("kein Absturz", False, str(ex)[:60])
print()

# --- 7) Die sicherheitskritische Eigenschaft
print("  7) SICHERHEIT: Ein Ausfall fuehrt NIE zu einem Kauf")
for label, jev_pf, allam_pf in [
    ("Jev Timeout", kaputt_jev, _orig_allam),
    ("Jev+Allam tot", kaputt_jev, kaputt_allam),
    ("Allam tot", _orig_jev, kaputt_allam),
]:
    ke.jev_entscheide, ke.allam_entscheide = jev_pf, allam_pf
    # Teste mit 12 Kandidaten, die alle "kaufen" sollten
    kaufte = 0
    for i in range(12):
        z = dict(GUTE_ZAHLEN)
        z["ticker"] = "T%d" % i
        z["score"] = 99.0
        z["mindestscore"] = 1.0
        try:
            e = ke.entscheide(z)
            if e.get("kaufen") is True and e.get("stufe") == "keine":
                kaufte += 1
        except Exception:
            pass
    pruefe("%-14s -> Stufe 'keine' kauft nie" % label, kaufte == 0,
           "Kaeufe aus Ausfall: %d" % kaufte)

ke.jev_entscheide, ke.allam_entscheide = _orig_jev, _orig_allam
print()
print("=" * 74)
print("  ERGEBNIS: %d/%d bestanden" % (bestanden, gesamt))
print("=" * 74)
sys.exit(0 if bestanden == gesamt else 1)
