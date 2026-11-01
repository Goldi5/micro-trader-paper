"""Zentraler Settings-Loader für Micro-Trader.

Alle Module lesen Einstellungen über diese Funktionen. Änderungen erfolgen
über dashboard.py (POST /api/settings), das validiert + Risikowarnungen erzeugt.

Sicherheitsphilosophie:
- Jeder Wert hat MIN/MAX-Grenzen (harte Blockade bei Verletzung).
- Kritische Werte (außerhalb empfohlenem Bereich, aber innerhalb MIN/MAX)
  erzeugen eine RISIKOWARNUNG, die der User im UI bestätigen muss.
- Module starten nicht mit kritischem Wert, ohne dass der User explizit
  "trotzdem speichern" gewählt hat.
"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE, "settings.json")

# ── Grenzen + empfohlene Bereiche (für Risikowarnung) ──
# (min, max, empfohlen_min, empfohlen_max, einheit, warnung_unter, warnung_ueber)
LIMITS = {
    "ki.konfidenz_cap":        (0, 100, 40, 90, "%", "KI wird bei hoher Selbsteinschätzung nicht mehr gebremst → Überhandel-Risiko", "KI fast lahmgelegt, kaum noch Käufe"),
    "ki.ki_temperatur":        (0.0, 0.5, 0.0, 0.3, "", "Sehr deterministisch, wenig Adaptivität", "Zu randomisiert, instabile Entscheidungen"),
    "ki.min_konfidenz_kaufen": (0, 100, 50, 80, "%", "Kauft bei niedriger Konfidenz → Rauschen", "Kauft fast nie"),
    "ki.exit_score_schwelle":  (0, 100, 50, 90, "", "Verkäufe kaum gebremst → Trend-Positionen zu früh raus", "Nichts wird mehr verkauft"),
    "ki.news_swap_min_score":  (0, 100, 50, 90, "", "News-Swap fast immer aktiv → zu viele Umschichtungen", "News-Swap fast nie aktiv"),
    "lernen.decay_lambda":     (0.0, 0.05, 0.005, 0.03, "/Tag", "Regeln verfallen kaum → alte Fehler bleiben ewig", "Regeln verfallen zu schnell → Lernen wirkungslos"),
    "lernen.anti_min_n":       (1, 20, 3, 10, "n", "Anti-Regeln aus Einzel-Spikes → Überreaktion", "Anti-Regeln brauchen ewig → Fehler wiederholt"),
    "lernen.min_samples":      (1, 50, 3, 15, "n", "Regeln aus zu wenig Daten → Rauschen/Überanpassung", "Regeln brauchen ewig → veraltet"),
    "lernen.anti_min_widerlegt_pct": (0, 100, 40, 80, "%", "Anti-Regeln zu schnell (schon ab wenig Widerlegung)", "Anti-Regeln zu selten"),
    "lernen.max_regeln":       (5, 200, 20, 60, "Stk", "Wenige Regeln → Lernen eingeschränkt", "Regel-Inflation → unübersichtlich"),
    "engine_bremsen.max_depot_pro_ticker": (1, 20, 2, 8, "Stk", "Konzentrations-Risiko: Ticker in zu vielen Depots", "Kaum noch Diversifikation möglich"),
    "engine_bremsen.drawdown_sperre_prozent": (5, 60, 15, 40, "%", "Depots frieren zu spät ein → große Verluste", "Depots frieren bei kleinem Rücksetzer ein"),
    "engine_bremsen.wochenende_handel": (None, None, None, None, "", None, None),
    "news.news_min_score":     (0, 100, 10, 40, "", "Fast alle News irrelevant → Blindflug", "Rauschen im News-Tab"),
    "news.news_max_alter_std": (1, 240, 12, 72, "h", "News zu kurz gültig", "Veraltete News beeinflussen noch"),
    # ── Finanzielle Parameter (Kategorien A, B, C) ──
    "kapital.gesamt_budget":   (100, 1000000, 1000, 100000, "€", "Sehr kleines Budget → wenig Diversifikation", "Sehr großes Budget → unübersichtlich"),
    "kapital.aktien_anteil":   (0, 100, 20, 60, "%", "Zu wenig Aktien-Exposure", "Zu viel Aktien-Risiko"),
    "kapital.etf_anteil":      (0, 100, 10, 50, "%", "Kaum stabiler Basis", "Zu passiv"),
    "kapital.spec_anteil":     (0, 100, 5, 50, "%", "Kaum Spekulations-Chance", "Zu spekulativ"),
    "kapital.max_gesamt_drawdown": (5, 60, 15, 40, "%", "Globaler Stopp zu spät → große Verluste", "Schon bei kleinem Rücksetzer eingefroren"),
    "depot_struktur.aktien_stufen": (1, 40, 5, 20, "Stk", "Wenige Stufen → grobe Risikogranularität", "Zu viele Stufen → unübersichtlich"),
    "depot_struktur.aktien_schritt": (1, 25, 5, 10, "Punkte", "Zu fein → viele leere Depots", "Zu grob → wenig Abstufung"),
    "depot_struktur.max_spec_depots": (1, 100, 10, 60, "Stk", "Wenig Spek-Diversifikation", "Zu viele Spec-Depots → Klumpenrisiko"),
    "risk_parameter.moderate_position_size": (0.05, 0.95, 0.20, 0.50, "", "Position zu klein → wenig Wirkung", "Position zu groß → Klumpenrisiko"),
    "risk_parameter.moderate_stop_loss": (0.50, 0.99, 0.85, 0.95, "", "Stopp zu eng → oft ausgestoppt", "Stopp zu weit → große Verluste"),
    "risk_parameter.moderate_take_profit": (1.01, 3.0, 1.05, 1.30, "", "TP zu nah → wenig Gewinn", "TP zu weit → Gewinn verpasst"),
    "risk_parameter.aggressive_position_size": (0.05, 0.95, 0.30, 0.60, "", "Position zu klein", "Position zu groß → hohes Risiko"),
    "risk_parameter.aggressive_stop_loss": (0.50, 0.99, 0.75, 0.90, "", "Stopp zu eng", "Stopp zu weit → Verluste"),
    "risk_parameter.aggressive_take_profit": (1.01, 3.0, 1.10, 1.40, "", "TP zu nah", "TP zu weit → Gewinn verpasst"),
}

# Boolesche Felder (keine Limits, nur Label)
BOOLS = {
    "ki.news_swap_aktiv": "News-Swap (Umschichtung bei hohem News-Impact)",
    "ki.multi_timeframe_lernen": "Multi-Timeframe-Lernen (Divergenz 15min/1d)",
    "engine_bremsen.wochenende_handel": "Wochenend-Handel (sonst alle Börsen zu)",
    "lernen.lern_modus": "auto|deterministisch|pausiert",
    "depot_struktur.etf_stufen_aktiv": "Liste der aktiven ETF-Stufen (Geldmarkt/Anleihen/Markt/Sektor/Thema/Gehebelt)",
}

# Boolesche Felder
BOOLS = {
    "ki.news_swap_aktiv": "News-Swap (Umschichtung bei hohem News-Impact)",
    "ki.multi_timeframe_lernen": "Multi-Timeframe-Lernen (Divergenz 15min/1d)",
    "engine_bremsen.wochenende_handel": "Wochenend-Handel (sonst alle Börsen zu)",
    "lernen.lern_modus": "auto|deterministisch|pausiert",
}

# ── Natürliche Namen + Erklärungen (für UI, Layman-verständlich) ──
# pfad -> (Anzeige-Name, Erklärung)
LABELS = {
    # KI
    "ki.konfidenz_cap": ("Max. Selbstvertrauen der KI",
        "Begrenzt, wie sicher die KI maximal sein darf. Niedriger Wert = die KI wird gebremst, wenn sie zu optimistisch ist (verkauft dann nicht zu früh aus Panik). Höher = KI darf selbst bei hoher Sicherheit handeln."),
    "ki.ki_temperatur": ("Kreativität der KI",
        "0 = die KI entscheidet immer gleich (sehr stabil, vorhersehbar). Höher = die KI variiert mehr, ist aber unruhiger und manchmal widersprüchlich."),
    "ki.min_konfidenz_kaufen": ("Mindest-Sicherheit zum Kaufen",
        "Die KI kauft nur, wenn sie sich zu mindestens X% sicher ist. Niedrig = kauft öfter auch bei Zweifel (Rauschen). Hoch = kauft nur bei sehr klarer Überzeugung."),
    "ki.exit_score_schwelle": ("Verkauf-Bremse (Trend-Schutz)",
        "Wenn ein Trade im Gewinn ist und der Trend hält, bremst dieser Wert den Verkauf. Niedrig = Trend-Positionen werden schnell verkauft. Hoch = nichts wird mehr verkauft, auch bei Schwäche."),
    "ki.news_swap_min_score": ("News-Schwelle für Umschichtung",
        "Ab welchem News-Score die KI eine Position umschichten darf (Verkauf trotz Haltedrang). Niedrig = oft aktiv (viele Umschichtungen). Hoch = fast nie."),
    "ki.news_swap_aktiv": ("News-Umschichtung an/aus",
        "Wenn an: Die KI verkauft eine Position, wenn wichtige News dagegen sprechen – auch wenn eigentlich 'halten' empfohlen war."),
    "ki.multi_timeframe_lernen": ("Lernen über verschiedene Zeitebenen",
        "Wenn an: Die KI lernt aus Widersprüchen zwischen kurzfristigem (15 Min) und langfristigem (1 Tag) Chart – erkennt so falsche Signale besser."),
    # Lernen
    "lernen.decay_lambda": ("Vergesslichkeit der KI (pro Tag)",
        "Wie schnell alte Regeln an Gewicht verlieren. Niedrig = die KI erinnert sich lange. Hoch = alte Erfahrungen verfallen schnell, das Lernen wird wirkungslos."),
    "lernen.anti_min_n": ("Mindest-Anzahl für Gegen-Regeln",
        "Aus wie vielen ähnlichen Fällen die KI erst eine 'Mach-das-nicht'-Regel ableitet. Niedrig = überreagiert auf einen einzelnen Fehler. Hoch = braucht viele Beweise."),
    "lernen.min_samples": ("Mindest-Stichprobe pro Regel",
        "Wie viele unabhängige Trades eine Regel mindestens haben muss, bevor sie als 'bestätigt' gilt. Niedrig = Regel aus Rauschen (Overfitting). Hoch = sehr konservativ, aber langsam."),
    "lernen.anti_min_widerlegt_pct": ("Widerlegungs-Schwelle für Gegen-Regeln",
        "Wie oft eine Regel falsch liegen muss, bis die KI sie als 'schlecht' markiert. Niedrig = Regeln werden schnell verworfen. Hoch = die KI hält an Fehlern fest."),
    "lernen.max_regeln": ("Maximale Anzahl gelernter Regeln",
        "Wie viele Regeln die KI maximal speichert. Wenige = lernt wenig. Zu viele = unübersichtlich, widersprüchlich."),
    "lernen.lern_modus": ("Lern-Modus",
        "auto = KI lernt normal. deterministisch = nur feste Regeln, keine neuen. pausiert = KI lernt gar nicht (nur Handeln mit Bestand)."),
    # Kapital
    "kapital.gesamt_budget": ("Gesamt-Budget",
        "Der Gesamtwert, den das System verwaltet (nur zur Orientierung/Anzeige). Ändert nichts an den echten Depots, hilft aber beim Rechnen von %-Anteilen."),
    "kapital.aktien_anteil": ("Anteil Aktien",
        "Wie viel % des Budgets in normale Aktien fließen soll. Niedrig = vorsichtig. Hoch = mehr Schwankung, mehr Chancen."),
    "kapital.etf_anteil": ("Anteil ETFs",
        "Wie viel % in breite Indexfonds (ruhiger, diversifiziert). Niedrig = wenig stabiler Basis. Hoch = sehr passiv."),
    "kapital.spec_anteil": ("Anteil Spekulation",
        "Wie viel % in riskante Zockereien (Krypto, Hebel, Meme). Niedrig = kaum Chance. Hoch = sehr spekulativ."),
    "kapital.max_gesamt_drawdown": ("Max. Gesamt-Verlust-Bremse",
        "Wenn das gesamte Portfolio um X% sinkt, frieren die Depots ein (kein Handel mehr). Niedrig = stoppt bei kleinem Rücksetzer. Hoch = große Verluste möglich, bevor gestoppt wird."),
    # Depot-Struktur
    "depot_struktur.aktien_stufen": ("Anzahl Aktien-Risikostufen",
        "Wie viele verschiedene Risikostufen (0–95) das System fährt. Mehr = feinere Abstufung, aber unübersichtlicher."),
    "depot_struktur.aktien_schritt": ("Abstand zwischen Stufen",
        "In welchen Schritten die Risikostufen steigen (z.B. 5 = 0,5,10,15…). Klein = viele leere Depots. Groß = grobe Sprünge."),
    "depot_struktur.max_spec_depots": ("Max. Spekulations-Depots",
        "Wie viele verschiedene Zockereien das System maximal gleichzeitig hält. Wenig = wenig Diversifikation. Viel = Klumpenrisiko."),
    "depot_struktur.etf_stufen_aktiv": ("Aktive ETF-Stufen",
        "Welche Risikoklassen bei ETFs gefahren werden (Geldmarkt = sicher bis Gehebelt = riskant)."),
    # Risk-Parameter
    "risk_parameter.moderate_position_size": ("Moderat: Positionsgröße",
        "Wie viel % des Depot-Geldes bei einem moderaten Trade investiert werden. Kleiner = vorsichtiger. Größer = mehr Wirkung, mehr Risiko."),
    "risk_parameter.moderate_stop_loss": ("Moderat: Stop-Loss",
        "Bei welchem Kursrutsch eine moderate Position automatisch verkauft wird (0.92 = -8%). Eng = oft ausgestoppt. Weit = größere Verluste möglich."),
    "risk_parameter.moderate_take_profit": ("Moderat: Take-Profit",
        "Bei welchem Kursanstieg eine moderate Position mit Gewinn verkauft wird (1.12 = +12%). Nah = schnell Gewinn mitnehmen. Weit = Gewinn verpasst bei Rücksetzer."),
    "risk_parameter.aggressive_position_size": ("Aggressiv: Positionsgröße",
        "Wie viel % bei einem aggressiven Trade investiert werden. Größer als moderat = höheres Risiko, höhere Chancen."),
    "risk_parameter.aggressive_stop_loss": ("Aggressiv: Stop-Loss",
        "Stop-Loss für aggressive Trades. Eng = schnell raus. Weit = mehr Verlust trotz Warnung."),
    "risk_parameter.aggressive_take_profit": ("Aggressiv: Take-Profit",
        "Take-Profit für aggressive Trades. Nah = Gewinn schnell sichern. Weit = mehr laufen lassen, aber Risiko."),
    # Engine-Bremsen
    "engine_bremsen.max_depot_pro_ticker": ("Max. Depots pro Titel",
        "In wie vielen Depots derselbe Ticker maximal liegen darf. Niedrig = Streuung (kein Klumpenrisiko). Hoch = wenig Diversifikation."),
    "engine_bremsen.drawdown_sperre_prozent": ("Drawdown-Sperre",
        "Wenn ein Depot um X% fällt, wird es eingefroren. Niedrig = friert bei kleinem Rücksetzer ein. Hoch = große Verluste, bevor gestoppt wird."),
    "engine_bremsen.wochenende_handel": ("Wochenend-Handel",
        "Wenn an: Das System handelt auch am Wochenende (Crypto/24h-Märkte). Sonst pausiert das System, wenn alle klassischen Börsen zu haben."),
    # News
    "news.news_min_score": ("News-Mindest-Score",
        "Ab welchem KI-Score eine News im News-Tab erscheint. Niedrig = fast alles (Blindflug). Hoch = nur wirklich relevante News, aber weniger Infos."),
    "news.news_max_alter_std": ("News-Maximalalter (Stunden)",
        "Wie lange eine News als relevant gilt. Kurz = verliert schnell an Bedeutung. Lang = veraltete News beeinflussen noch Entscheidungen."),
}


def lade_settings():
    """Lädt settings.json (mit Fallback auf Defaults bei Fehler)."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "ki": {"konfidenz_cap": 60, "ki_temperatur": 0.1, "min_konfidenz_kaufen": 60,
                   "exit_score_schwelle": 70, "news_swap_aktiv": True,
                   "news_swap_min_score": 75, "multi_timeframe_lernen": True},
            "lernen": {"decay_lambda": 0.01, "anti_min_n": 5, "anti_min_widerlegt_pct": 60, "min_samples": 5,
                       "max_regeln": 40, "lern_modus": "auto"},
            "engine_bremsen": {"max_depot_pro_ticker": 4, "drawdown_sperre_prozent": 30,
                               "wochenende_handel": False},
            "news": {"news_min_score": 20, "news_max_alter_std": 48},
        }


def _get_nested(d, pfad):
    for k in pfad.split("."):
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _set_nested(d, pfad, wert):
    parts = pfad.split(".")
    for k in parts[:-1]:
        d = d.setdefault(k, {})
    d[parts[-1]] = wert


def validiere_und_risiko(neue):
    """Validiert neue Settings.

    Return: (ok, fehler_liste, warnungen_liste, kritische_felder)
    - ok: False wenn harte Grenze verletzt (Speichern blockiert)
    - warnungen: Risikowarnungen (Speichern nur nach Bestätigung)
    - kritische_felder: Liste der Pfade, die eine Warnung auslösen
    """
    fehler = []
    warnungen = []
    kritische = []

    for pfad, (mn, mx, emn, emx, einheit, w_unter, w_ueber) in LIMITS.items():
        if pfad in BOOLS:
            continue
        wert = _get_nested(neue, pfad)
        if wert is None:
            continue
        # Harte Grenze
        if mn is not None and wert < mn:
            fehler.append(f"{pfad}={wert} unter Minimum {mn}{einheit}")
            continue
        if mx is not None and wert > mx:
            fehler.append(f"{pfad}={wert} über Maximum {mx}{einheit}")
            continue
        # Empfohlener Bereich → Risikowarnung
        if emn is not None and wert < emn and w_unter:
            warnungen.append(f"⚠️ {pfad}={wert}{einheit}: {w_unter}")
            kritische.append(pfad)
        elif emx is not None and wert > emx and w_ueber:
            warnungen.append(f"⚠️ {pfad}={wert}{einheit}: {w_ueber}")
            kritische.append(pfad)

    # Boolesche / Modus-Check
    modus = _get_nested(neue, "lernen.lern_modus")
    if modus is not None and modus not in ("auto", "deterministisch", "pausiert"):
        fehler.append(f"lernen.lern_modus='{modus}' ungültig (auto|deterministisch|pausiert)")

    return (len(fehler) == 0, fehler, warnungen, kritische)


def speichere_settings(neue, bestaetigt=False):
    """Speichert neue Settings, wenn validiert (und bei Warnungen bestätigt).

    Return: (ok, meldung, warnungen)
    """
    ok, fehler, warnungen, kritische = validiere_und_risiko(neue)
    if not ok:
        return (False, "Blockiert wegen Grenzverletzung: " + "; ".join(fehler), warnungen)
    if kritische and not bestaetigt:
        return (False, "Risikowarnung(en) müssen bestätigt werden: " + "; ".join(warnungen), warnungen)
    # Speichern
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(neue, f, ensure_ascii=False, indent=2)
        return (True, "Einstellungen gespeichert", warnungen)
    except Exception as e:
        return (False, f"Speicherfehler: {e}", warnungen)


# ── Hilfsfunktionen für Module (Default-Fallback) ──
def ki(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"ki.{name}")
    return v if v is not None else default

def lernen(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"lernen.{name}")
    return v if v is not None else default

def bremse(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"engine_bremsen.{name}")
    return v if v is not None else default

def news_opt(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"news.{name}")
    return v if v is not None else default

def kapital(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"kapital.{name}")
    return v if v is not None else default

def depot_struktur(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"depot_struktur.{name}")
    return v if v is not None else default

def risk_param(name, default=None):
    s = lade_settings()
    v = _get_nested(s, f"risk_parameter.{name}")
    return v if v is not None else default
