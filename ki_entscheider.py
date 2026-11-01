"""KI-Entscheider: Jev (direkt) als Primaerinstanz, mit Rueckfallkette.

ANLASS (2026-09-29):
  typesafe/jev-router war schnell, aber unbrauchbar: Reasoning-Tokens
  fressen 250 von 300 max_tokens, die Antwort wird abgeschnitten
  (11/36 bei max_tokens=300), und die Modellwahl ist nicht steuerbar
  (models=[...] wird nachweislich ignoriert).

  Jev DIREKT ueber /api/alpha/decisions liefert stattdessen einen
  noul-Wert (Wahrscheinlichkeit 0..1) in einem festen Schema:

      {"answers": {"kauf": {"type": "noul", "noul": 0.61}},
       "usage": {"input_tokens": 396, "output_tokens": 21, "cost": 0.0000166}}

  Gemessen an 12 realen Depot-Kandidaten: 0,26 s Median (statt 1,92 s),
  24/24 strukturell parsebar, 0,72 USD/Jahr (statt 19,02).

WARUM EINE EIGENE INSTANST UND KEIN ERSATZ IM BESTEHENDEN PFAD:
  Der Bestand ruft ein Textmodell mit einem 5-Depots-Prompt und erwartet
  ein JSON-Array mit Aktionen. Jev liefert pro Frage einen noul-Wert,
  keine Aktionenliste. Beides mischt man nicht.

SICHERHEIT:
  - Jev entscheidet NUR darueber, OB ein Kandidat gekauft wird.
  - WIEVIEL und OBUEBERHAUPT entscheidet risk_controller.py, unveraendert.
  - Jev darf keine Kaufmenge, keinen Stop-Loss und keine Positiongroesse
    liefern - es kennt diese Groessen nicht.
  - Ohne Freigabe (PAPER_ONLY) wird nichts ausgefuehrt.

RUECKFALLKETTE (jede Stufe wird protokolliert):
  1. jev-direkt      noul >= Schwelle  -> kaufen
  2. groq/allam-2-7b  JSON kaufen/hold  -> kaufen (0,2 s, frei)
  3. risk_controller  Klartext-Regel    -> nur als letzter Ausweg
  Stufe 3 ist KEIN Freigeben, sondern das Stoppen: es heisst "nicht kaufen".
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

# --- Konfiguration -------------------------------------------------------
# Schwellwert fuer den noul-Wert. Bewusst NICHT 0,50: gemessen lagen
# klare Kaufe bei 0,51..0,70 und ein Grenzfall bei 0,45..0,47. Mit 0,50
# wuerde der Grenzfall an der Grenze pendeln. 0,55 ist die konservative
# Wahl - lieber eine Entscheidung dem Risk-Controller ueberlassen als
# einen Grenzfall kaufen.
JEV_SCHWELLE = float(os.environ.get("JEV_SCHWELLE", "0.55"))

JEV_MODELL = "typesafe/jev-1.13"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_TIMEOUT = float(os.environ.get("JEV_TIMEOUT", "20"))

# Allam-2-7b als Rueckfall: 0,2 s, valides JSON, kostenlos (Groq)
ALLAM_URL = "https://api.groq.com/openai/v1/chat/completions"
ALLAM_MODELL = "allam-2-7b"
ALLAM_TIMEOUT = float(os.environ.get("ALLAM_TIMEOUT", "15"))

# Zeitmessung fuer das Logfile
_MESSUNG = {"jev": [], "allam": []}


def _key(name: str) -> str:
    """API-Key aus .env lesen, ohne ihn zu loggen."""
    pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    with open(pfad, encoding="utf-8") as fh:
        for zeile in fh:
            zeile = zeile.strip()
            if zeile.startswith(name + "="):
                return zeile.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("Key %s fehlt in .env" % name)


_KEY_CACHE: dict = {}


def key(name: str) -> str:
    if name not in _KEY_CACHE:
        _KEY_CACHE[name] = _key(name)
    return _KEY_CACHE[name]


# --- Stufe 1: Jev direkt -------------------------------------------------
def jev_entscheide(kennzahlen: dict, schwelle: float | None = None) -> dict:
    """Jev ueber /api/alpha/decisions. Liefert strukturierte noul-Wahrscheinlichkeit.

    Rueckgabe: {"stufe": "jev", "p": 0.61, "kaufen": bool, "grund": str,
                "sekunden": 0.26, "kosten_usd": 0.0000166, "modell": str}
    Wirft bei Fehlern - der Aufrufer entscheidet ueber den Rueckfall.
    """
    grenze = JEV_SCHWELLE if schwelle is None else schwelle
    koerper = {
        "model": JEV_MODELL,
        "state": kennzahlen,
        "questions": {
            "kauf": {
                "type": "noul",
                "instructions": (
                    "Antworte mit der Wahrscheinlichkeit, dass ein Kauf "
                    "dieses Titers bei diesen Zahlen sinnvoll ist."
                ),
            }
        },
    }
    t0 = time.time()
    req = urllib.request.Request(
        JEV_URL,
        data=json.dumps(koerper).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key("OPENROUTER_API_KEY"),
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=JEV_TIMEOUT)
    dat = json.loads(resp.read().decode("utf-8"))
    dt = time.time() - t0

    p = dat["answers"]["kauf"]["noul"]
    if not isinstance(p, (int, float)) or not 0.0 <= float(p) <= 1.0:
        raise ValueError("noul ausserhalb 0..1: %r" % (p,))
    usage = dat.get("usage") or {}
    return {
        "stufe": "jev",
        "p": float(p),
        "kaufen": float(p) >= grenze,
        "grund": "Jev-Wahrscheinlichkeit %.2f (Schwelle %.2f)" % (float(p), grenze),
        "sekunden": round(dt, 3),
        "kosten_usd": usage.get("cost", 0.0),
        "tokens": usage.get("input_tokens", 0),
        "modell": dat.get("model", JEV_MODELL),
    }


# --- Stufe 2: Allam-2-7b als Rueckfall ----------------------------------
def allam_entscheide(kennzahlen: dict) -> dict:
    """Groq allam-2-7b. Erwartet dieselben Zahlen, antwortet mit JSON.

    WICHTIG (2026-09-29): eigener urllib-Aufruf schlug mit HTTP 403
    "error code: 1010" fehl. Das ist eine Cloudflare-Blockade des
    Standard-Python-User-Agents, kein abgelaufener Key. Gegenprobe:
      ohne User-Agent -> HTTP 403
      mit  User-Agent -> HTTP 200
    Deshalb laeuft der Rueckfall ueber ki_provider, das den Header
    bereits setzt. Kein zweiter Key, keine eigene Providerpflege.
    """
    zeilen = "\n".join("%s: %s" % (k, v) for k, v in kennzahlen.items())
    prompt = (
        "Du bekommst nur Zahlen. Entscheide danach einen Kauf.\n"
        "%s\n"
        "Antworte ausschliesslich mit einem JSON-Objekt, ohne Codeblock, "
        'ohne Text: {"kaufen": true oder false, "konfidenz": 0-100, '
        '"grund": "maximal 15 Woerter"}' % zeilen
    )
    t0 = time.time()

    # Weg 1: der bestehende Pool (hat den noetigen User-Agent)
    try:
        import ki_provider as kp
        pool = kp.provider_liste()
        bevorzugt = [p for p in pool
                     if "groq" in str(p.get("base_url", "")).lower()]
        if bevorzugt:
            client = kp.get_client(bevorzugt[0])
            roh, fehler = kp._ki_call(client, bevorzugt[0],
                                      [{"role": "user", "content": prompt}],
                                      0.0, 300, ALLAM_MODELL)
            if roh:
                return _allam_auswerten(roh, time.time() - t0)
            raise RuntimeError("ki_provider: %s" % (fehler or "leer"))
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        fehler_pool = str(e)[:120]

    # Weg 2: direkter Aufruf mit dem User-Agent, den ki_provider nutzt
    try:
        import ki_provider as kp2
        ua = getattr(kp2, "UA", "Mozilla/5.0")
    except Exception:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

    koerper = {
        "model": ALLAM_MODELL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        ALLAM_URL,
        data=json.dumps(koerper).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key("GROQ_API_KEY"),
            "Content-Type": "application/json",
            "User-Agent": ua,
        },
    )
    resp = urllib.request.urlopen(req, timeout=ALLAM_TIMEOUT)
    dat = json.loads(resp.read().decode("utf-8"))
    return _allam_auswerten(
        (dat.get("choices") or [{}])[0].get("message", {}).get("content") or "",
        time.time() - t0)


def _allam_auswerten(text: str, dt: float) -> dict:
    import re
    m = re.search(r'"kaufen"\s*:\s*(true|false)', text, re.I)
    if not m:
        raise ValueError("Allam-Antwort ohne kaufen-Feld: %r" % text[:120])
    k = re.search(r'"konfidenz"\s*:\s*(\d+)', text)
    g = re.search(r'"grund"\s*:\s*"([^"]*)"', text)
    return {
        "stufe": "allam",
        "p": None,
        "kaufen": m.group(1).lower() == "true",
        "grund": (g.group(1) if g else "Allam-2-7b")[:80],
        "konfidenz": int(k.group(1)) if k else None,
        "sekunden": round(dt, 3),
        "tokens": 0,
        "modell": ALLAM_MODELL,
    }


# --- Kette ---------------------------------------------------------------
def entscheide(kennzahlen: dict, schwelle: float | None = None,
               mit_rueckfall: bool = True) -> dict:
    """Jev zuerst. Bei Fehlschlag Allam. Bei dessen Fehlschlag: nicht kaufen.

    Wichtig: der letzte Ausgang ist IMMER "nicht kaufen". Ein Ausfall der
    KI darf nie dazu fuehren, dass etwas gekauft wird - das waere das
    gefaehrlichste Verhalten im ganzen System.
    """
    # Stufe 1
    try:
        erg = jev_entscheide(kennzahlen, schwelle)
        _MESSUNG["jev"].append(erg["sekunden"])
        return erg
    except Exception as e1:  # noqa: BLE001 - bewusst breit, wir fallen zurueck
        fehler1 = str(e1)[:160]

    if mit_rueckfall:
        # Stufe 2
        try:
            erg = allam_entscheide(kennzahlen)
            _MESSUNG["allam"].append(erg["sekunden"])
            erg["rueckfall_grund"] = "Jev: " + fehler1
            return erg
        except Exception as e2:  # noqa: BLE001
            fehler2 = str(e2)[:160]
    else:
        fehler2 = "kein Rueckfall gewuenscht"

    # Stufe 3: nichts kaufen. Kein weiterer Versuch.
    return {
        "stufe": "keine",
        "p": None,
        "kaufen": False,
        "grund": "Beide KI-Instanzen ausgefallen - nicht kaufen",
        "sekunden": 0.0,
        "fehler_jev": fehler1,
        "fehler_allam": fehler2,
    }


def messung() -> dict:
    """Latenz-Uebersicht je Stufe. Nur zum Protokollieren."""
    import statistics
    aus = {}
    for stufe, werte in _MESSUNG.items():
        if werte:
            aus[stufe] = {
                "n": len(werte),
                "median_s": round(statistics.median(werte), 3),
                "max_s": round(max(werte), 3),
            }
    return aus
