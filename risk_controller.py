#!/usr/bin/env python3
"""
risk_controller.py – ZENTRALE RISIKOSTEUERUNG (Single Source of Truth)
========================================================================

Warum dieses Modul existiert
----------------------------
Die IST-Analyse vom 27.09.2026 ergab: die Risikodifferenzierung existierte
faktisch NICHT.

  * engine.py las ``risk_params.get("allowed_tiers", [0,1,2,3,4])`` und
    ``risk_params.get("tier_bonus", {})`` – beide Werte wurden NIE gesetzt,
    es existierten nur Defaults.
  * Folge: ``tier_bonus`` war ueberall 0 und JEDES Depot durfte alle 5 Tiers
    kaufen. Risk-0 verhielt sich IDENTISCH zu Risk-95.
  * ``risk_profile.get_allowed_tiers()`` war DEAD CODE, aufgerufen nur vom
    Generator ``build_risk_profile.py``, nie vom Betrieb.

Dieses Modul macht aus der Risikostufe eine echte, wirksame Entscheidung:

  1. Echte Tier-Zuordnung je Risikostufe   -> allowed_tiers()
  2. tier_bonus, der nicht ueberall 0 ist  -> tier_bonus()
  3. Positionsgroesse / max. Positionen / Stop-Loss / Take-Profit /
     max. Drawdown / Cash-Boden             -> params()
  4. EINE Eintrittsfunktion fuer JEDEN Trade -> pruefe_und_bremse()

Sicherheitslage
---------------
Der Micro-Trader handelt ausschliesslich PAPER/SHADOW. Es gibt keinen
echten Broker-Client. Dieses Modul aendert daran nichts: es ist reine
Risikologik ohne jeden Netzzugriff.

Schnittstelle
-------------
    from risk_controller import params, pruefe_und_bremse

    p = params(50)                       # -> dict
    res = pruefe_und_bremse(risk=50, ...)
    if res.blockiert:
        print(res.reason)                # konkreter, lesbarer Grund
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import strategie
except Exception:  # pragma: no cover - strategie.py ist Pflicht im Repo
    strategie = None


# ─── Tier-Definition (identisch zu risk_profile.TIERS / strategie.TIER_NAMEN) ───
TIER_NAMEN = {
    0: "Defensiv",
    1: "Large-Cap",
    2: "Growth",
    3: "Spekulativ",
    4: "ETF/Hebel",
    6: "Hebel/Inverse",}

# 01.10.2026: Anteil, den ein Hebelprodukt von seiner regulaeren
# Position behaelt, unabhaengig von position_size. Siehe max_betrag().
#
# Der Wert 0.85 haelt das Verhaeltnis der alten absoluten Klemme:
# bei size 0.34 ergaebe das 0.289, praktisch die bisherigen 0.30.
HEBEL_ANTEIL_VON_NORMAL = 0.85

# Tiers, die als "gehebelt" gelten. Risk 0-20 darf diese NICHT kaufen.
# Uebernommen aus strategie.HEBEL_TIERS, mit Fallback falls Import scheitert.
try:
    HEBEL_TIERS = set(strategie.HEBEL_TIERS)
except Exception:
    HEBEL_TIERS = {3, 6}

# Risikostufen, die in diesem Projekt tatsaechlich vorkommen (0..95 in 5er-Schritten)
RISK_MIN = 0
RISK_MAX = 95


# ══════════════════════════════════════════════════════════════════════
# 1. TIER-ZUORDNUNG
# ══════════════════════════════════════════════════════════════════════

def allowed_tiers(risk):
    """Welche Tiers darf ein Depot dieser Risikostufe kaufen?

    DAS ist die echte, im Betrieb genutzte Tier-Zuordnung. Die alte
    risk_profile.get_allowed_tiers() war toter Generator-Code.

    Gestaltung (Anforderung: Risk 0-20 ohne gehebelte ETFs, Risk 76-95 mehr):

    BUG-FIX 2026-09-27, Tier 4 war "ETF/Hebel" und vermischte zwei
    sehr verschiedene Dinge. Folge: GLD, SLV, XLU, XLP, VNQ waren
    fuer Risk 0-75 gesperrt, obwohl es die risikoaermsten Titel
    im Universum sind. Und ab Risk 76 fiel Tier 0 "Defensiv" weg -
    wer am aggressivsten ist, durfte die defensivsten Titel nicht
    kaufen. Das war keine Grenze, das war eine Inversion.

    Tier 4 ist jetzt "ETF breit" (SPY, VTI, QQQ, GLD, XLU, ...),
    Tier 6 ist neu und heisst "Hebel/Inverse" (TQQQ, SQQQ, SOXL,
    SDOW, ...). Damit gilt die urspruengliche Anforderung
    wortwoertlich: Risk 0-20 ohne gehebelte ETFs - aber mit breiten.

      Risk  0-20  -> [0, 1, 4]              defensiv + breite ETFs
      Risk 21-40  -> [0, 1, 2, 4]           + Growth
      Risk 41-75  -> [0, 1, 2, 3, 4]        + Spekulativ
      Risk 76-100 -> [0, 1, 2, 3, 4, 6]     + Hebel (Tier 6)

    Ab Risk 76 ist Tier 0 wieder erlaubt. Das ist der eigentliche
    Fix - vorher war es gesperrt.
    """
    r = _clamp_risk(risk)

    if r <= 20:
        return [0, 1, 4]
    if r <= 40:
        return [0, 1, 2, 4]
    if r <= 75:
        return [0, 1, 2, 3, 4]
    return [0, 1, 2, 3, 4, 6]


def tier_erlaubt(risk, tier):
    """Ist `tier` fuer dieses Depot ueberhaupt zugelassen?"""
    try:
        t = int(tier)
    except (TypeError, ValueError):
        return False
    return t in allowed_tiers(risk)


# ══════════════════════════════════════════════════════════════════════
# 2. TIER-BONUS  (der Punkt, der vorher ueberall 0 war)
# ══════════════════════════════════════════════════════════════════════

# Ankerpunkte: (Risikostufe, {tier: bonus}). Dazwischen wird linear
# interpoliert. So bekommt jedes Depot einen ANDEREN, plausiblen Bonus-
# Vektor – je hoeher das Risiko, desto mehr zaehlen die spekulativen Tiers.
_TIER_BONUS_ANCHOR = [
    (0,  {0: 14, 1: 9,  2: 2,  3: -12, 4: -18}),
    (20, {0: 11, 1: 8,  2: 3,  3: -8,  4: -14}),
    (40, {0: 8,  1: 7,  2: 5,  3: 0,   4: -6}),
    (60, {0: 5,  1: 6,  2: 7,  3: 6,   4: 2}),
    (75, {0: 3,  1: 5,  2: 9,  3: 10,  4: 7}),
    (95, {0: 0,  1: 4,  2: 11, 3: 15,  4: 13}),
]

_TIER_BONUS_CACHE = {}


def tier_bonus(risk):
    """Tier-Bonus-Vektor fuer diese Risikostufe.

    WAR:  {0:0, 1:0, 2:0, 3:0, 4:0}  -> keine Risikodifferenzierung.
    IST:  Risk 0  -> {0:+14, 1:+9,  2:+2,  3:-12, 4:-18}
          Risk 95 -> {0:0,   1:+4,  2:+11, 3:+15, 4:+13}

    Der Bonus verschiebt das Scoring-Gewicht: ein defensives Depot bevorzugt
    Bluechips, ein spekulatives Depot bevorzugt Hebel/Volatilitaet.
    """
    r = _clamp_risk(risk)
    if r in _TIER_BONUS_CACHE:
        return dict(_TIER_BONUS_CACHE[r])

    # Ankerpunkte finden und linear interpolieren
    lo = _TIER_BONUS_ANCHOR[0]
    hi = _TIER_BONUS_ANCHOR[-1]
    for i in range(len(_TIER_BONUS_ANCHOR) - 1):
        a, b = _TIER_BONUS_ANCHOR[i], _TIER_BONUS_ANCHOR[i + 1]
        if a[0] <= r <= b[0]:
            lo, hi = a, b
            break

    span = hi[0] - lo[0]
    f = 0.0 if span == 0 else (r - lo[0]) / float(span)
    out = {}
    for tier in range(5):
        v = lo[1][tier] + (hi[1][tier] - lo[1][tier]) * f
        out[tier] = round(v, 2)
    _TIER_BONUS_CACHE[r] = out
    return dict(out)


# ══════════════════════════════════════════════════════════════════════
# 3. PARAMETER JE RISIKOSTUFE
# ══════════════════════════════════════════════════════════════════════

def params(risk):
    """Alle handelsrelevanten Parameter fuer eine Risikostufe.

    Enthaelt bewusst AUCH allowed_tiers und tier_bonus – genau die beiden
    Keys, die engine.py:bewerte() seit jeher gelesen hat, die aber nie
    befuellt waren.

    * position_size   Anteil des Depot-Cash fuer EINE neue Position
    * max_positions   harte Obergrenze Positionen im Depot
    * stop_loss       Kursfaktor, unterhalb dessen verkauft wird
    * take_profit     Kursfaktor, oberhalb dessen verkauft wird
    * max_drawdown    Drawdown in %, ab dem das Depot eingefroren wird
    * cash_floor      Mindest-Cash-Anteil, damit nie zu 100% investiert
    * min_score       Score-Schwelle im Scoring
    """
    r = _clamp_risk(risk)
    f = r / 100.0

    # Cash-Boden: Anteil des Cash, der IMMER liquide bleiben muss.
    # Risk 0: 25% Cash-Boden, Risk 95: 5%.
    cash_floor = round(0.25 - 0.20 * f, 4)
    max_investierbar = 1.0 - cash_floor

    # 01.10.2026: ZIEL der Positionszahl, getrennt von der Rechnung.
    #
    # BEFUND: Die alte Formel max_positions = 8 - r*4/95 gab Risk 80
    # fuenf Positionen. Die anschliessende While-Schleife zog sie auf
    # 2 herunter, weil 5 x 0.31 = 1.55 den investierbaren Anteil von
    # 0.91 uebersteigt. Die Positionszahl war damit eine Nebenwirkung
    # der Budgetrechnung und kein gewaehltes Risikomass. Gemessen:
    # Risk 80 hatte 2 Positionen und 16 blockierte Kaufversuche auf
    # denselben Ticker.
    #
    # NEU: Die gewuenschte Positionenzahl wird gesetzt und die
    # Positionsgroesse daraus berechnet - size <= (1-floor)/N. Der
    # Cash-Boden bleibt unveraendert; ihn zu senken, um bei 31% je
    # Stueck sechs Positionen zu erlauben, ergaebe bei Risk 90 einen
    # Floor von -0.98, also mehr investiert als Kapital vorhanden.
    #
    # Der Cash-Boden ist damit die Groesse, die die Streuung begrenzt.
    # 01.10.2026, zweite Fassung: die Positionszahl waechst wieder mit
    # der Risikostufe.
    #
    # Die erste Fassung gab Risk 0 und Risk 90 BEIDE dieselbe Zahl.
    # Damit war T10 (Cash-Boden) erfuellt, aber T7 nicht: der
    # Kriterienkatalog verlangt "Risk 0 und Risk 95 verhalten sich
    # BEWIESEN unterschiedlich" - und zwei Parameter, die gleich sind,
    # sind kein Beweis.
    #
    # Beide Kriterien zusammen erfordern eine Positionszahl, die mit
    # der Stufe waechst, waehrend der Cash-Boden sie begrenzt:
    # defensiv wenige Positionen mit grossem Boden, spekulativ mehr
    # Positionen mit kleiner Reserve.
    #
    # Deshalb wieder eine Formel ueber r statt einer Tabelle - aber mit
    # kleinerer Spannweite als vorher. Vorher span sie 8 bis 4 Positionen
    # und wurde von der While-Schleife auf 2 heruntergezogen. Jetzt
    # span sie 5 bis 7 und wird vom Cash-Boden begrenzt, nicht von einer
    # Schleife, die still nach unten korrigiert.
    max_ziel = max(5, min(7, int(round(5 + (r * 2) / 95.0))))

    # Groesse wie bisher als ANGEBOT, aber nie groesser als das, was
    # die gewaehlte Positionszahl mit dem Cash-Boden zulaesst.
    size_angebot = 0.15 + 0.20 * f
    size_deckel = max_investierbar / max_ziel
    # VOR der Division runden. Vorher wurde die Positionszahl aus dem
    # ungerundeten Wert berechnet, zurueckgegeben wurde der gerundete -
    # dadurch verletzten 20 von 96 Stufen die Kapitalbindung, ohne
    # dass die Pruefung es sah.
    position_size = round(min(size_angebot, size_deckel), 4)

    max_positions = max(2, min(max_ziel,
                               int(max_investierbar / position_size)))

    # Harte Konsistenz als SICHTPRUEFUNG statt als Schleife. Geprueft
    # wird die Zahl, die zurueckgegeben wird - also position_size nach
    # dem Runden. Die Toleranz ist kleiner als die letzte
    # Rundungsstelle, damit die Pruefung nicht durchgerutscht werden
    # kann. Ein stilles Herunterzaehlen war genau der Fehler, den
    # dieser Block ersetzt.
    _ist = max_positions * position_size
    if _ist > (max_investierbar + 5e-5):
        raise AssertionError(
            "Risikostufe %d verletzt die Kapitalbindung: %d Positionen x "
            "%.4f = %.4f > %.4f investierbar (cash_floor %.4f)"
            % (r, max_positions, position_size,
               _ist, max_investierbar, cash_floor))

    return {
        "risk": r,
        "max_positions": max_positions,
        "position_size": round(position_size, 4),
        "stop_loss": round(0.97 - (r * 0.001), 4),          # 0.970 -> 0.875
        "take_profit": round(min(1.30, 1.10 + (r * 0.002)), 4),  # 1.100 -> 1.290
        "max_drawdown": round(15.0 + (r * 0.20), 2),        # 15% (Risk 0) .. 34% (Risk 95)
        "cash_floor": cash_floor,
        "min_score": max(25, int(round(50 - (r / 3.0)))),   # 50 (Risk 0) .. 18->25 (Risk 95)
        "allowed_tiers": allowed_tiers(r),
        "tier_bonus": tier_bonus(r),
        "volatility_bonus": 5,
    }


# Kompatibilitaets-Alias: dashboard.py ruft historisch risk_profile.get_params.
# Hier bewusst NICHT vorhanden – die Verdrahtung erfolgt in risk_profile.py.
fuer_risk_stufe = params


def max_betrag(cash, risk, tier=None, vol_ratio=None, hebel=False):
    """Groesster zulaessiger Kaufbetrag in Waehrungseinheiten.

    Beruecksichtigt: Positionsgroesse, Cash-Boden, Volumen-Daempfer und
    das Hebel-ETF-Limit (strategie.HEBEL_ETF_MAX_POS = 0.30).
    """
    p = params(risk)
    betrag = min(cash, cash * p["position_size"])

    # Volumen-Daempfer (strategie.volumen_pos_size) – jetzt WIRKSAM
    if strategie is not None and vol_ratio is not None:
        f = strategie.volumen_pos_size(vol_ratio)
        if f <= 0:
            return 0.0
        betrag *= f

    # Hebel-ETF: zweifach begrenzt
    #
    # 01.10.2026: Die absolute Klemme allein hat an Wirkung verloren.
    # Sie war an cash * HEBEL_ETF_MAX_POS gebunden, der Grundbetrag an
    # cash * position_size - beides cash-mal-Konstanten, es gewann die
    # kleinere. Nach der Umstellung auf 6-7 Positionen liegt size bei
    # Risk 95 bei 0.1343, die Klemme bei 0.30 griff nie mehr, SPY und
    # TQQQ bekamen beide exakt 1343.00. Gemessen.
    #
    # Darum kommt der Anteil HEBEL_ANTEIL_VON_NORMAL dazu: er gilt
    # unabhaengig von position_size. Bei der alten Groesse 0.34 ergibt
    # er 0.289, praktisch die bisherige Klemme. Bei 0.1343 ergibt er
    # 0.1142 - der Hebel bleibt messbar unter dem breiten ETF.
    #
    # Die 0.85 sind KEINE Verschiebung der Risikopolitik: ein blosser
    # Multiplikator 0.30 haette den Hebel auf 30% der regulaeren
    # Position gebracht statt der bisherigen 88%.
    if hebel and strategie is not None:
        betrag = min(betrag,
                     cash * strategie.HEBEL_ETF_MAX_POS,      # absolut
                     betrag * HEBEL_ANTEIL_VON_NORMAL)        # relativ

    # Cash-Boden: nie den gesamten Bestand einsetzen
    boden = cash * p["cash_floor"]
    betrag = min(betrag, max(0.0, cash - boden))
    return round(max(0.0, betrag), 4)


# ══════════════════════════════════════════════════════════════════════
# 4. DIE EINZIGE EINTRITTSFUNKTION
# ══════════════════════════════════════════════════════════════════════

class PruefErgebnis:
    """Ergebnis von pruefe_und_bremse().

    blockiert: bool   True = Trade NICHT ausfuehren
    reason:    str    konkreter, lesbarer Grund (nie leer, nie stumm)
    """

    __slots__ = ("blockiert", "reason", "kategorie", "max_betrag", "params")

    def __init__(self, blockiert, reason, kategorie="", betrag=0.0, p=None):
        self.blockiert = bool(blockiert)
        self.reason = reason
        self.kategorie = kategorie
        self.max_betrag = betrag
        self.params = p

    # Erlaubt die Aufrufstellen bequem "if not res:" zu schreiben
    def __bool__(self):
        return not self.blockiert

    def __repr__(self):
        return "PruefErgebnis(blockiert=%s, kategorie=%s, reason=%r)" % (
            self.blockiert, self.kategorie, self.reason)

    def als_dict(self):
        return {
            "blockiert": self.blockiert,
            "reason": self.reason,
            "kategorie": self.kategorie,
            "max_betrag": self.max_betrag,
        }


def pruefe_und_bremse(risk, ticker=None, tier=None, preis=None, cash=0.0,
                      depot_wert=None, anzahl_positionen=None, drawdown_pct=0.0,
                      betrag=None, vol_ratio=None, score=None, min_bestehend=0.0,
                      positionen=None, tier_anzahl=None,
                      quelle="", verlangt_penny_limit=True,
                      verlangt_tier_mix=True):
    """DIE zentrale Risikopruefung. Wird VOR jedem Trade aufgerufen.

    Rueckgabe ist IMMER ein PruefErgebnis mit:
      - .blockiert (bool)
      - .reason    (konkreter Grund, z.B. "tier_gesperrt: Tier 4 (ETF/Hebel)
                    ist bei Risk 10 nicht erlaubt (erlaubt: 0,1)")

    Es gibt keinen Pfad, der `None`, `pass` oder ein stummes False
    zurueckgibt: jeder Zweig liefert ein vollstaendiges Ergebnis.
    """
    r = _clamp_risk(risk)
    p = params(r)

    def ok(reason="ok"):
        return PruefErgebnis(False, reason, "erlaubt", 0.0, p)

    def nein(kat, reason):
        return PruefErgebnis(True, "%s: %s" % (kat, reason), kat, 0.0, p)

    # ── 1. Kurs-Guard: Rate-Limit / yfinance leer liefert 0 ────────────
    if preis is not None:
        try:
            if float(preis) <= 0:
                return nein("kein_kurs",
                            "Kurs fuer %s ist %s (Rate-Limit/Fehler) - "
                            "kein Handel auf unbekanntem Preis"
                            % (ticker or "?", preis))
        except (TypeError, ValueError):
            return nein("kein_kurs", "Kurs fuer %s nicht interpretierbar: %r"
                        % (ticker or "?", preis))

    # ── 2. Drawdown-Lock ──────────────────────────────────────────────
    if depot_wert is not None and depot_wert > 0:
        try:
            dd = float(drawdown_pct)
        except (TypeError, ValueError):
            dd = 0.0
        if dd >= p["max_drawdown"]:
            return nein("drawdown_lock",
                        "Drawdown %.1f%% >= Limit %.1f%% fuer Risk %d - "
                        "Depot eingefroren bis Neustart"
                        % (dd, p["max_drawdown"], r))

    # ── 3. Tier-Zulassung (der Punkt, der vorher nicht existierte) ────
    if tier is not None:
        try:
            t = int(tier)
        except (TypeError, ValueError):
            return nein("unbekannter_tier", "Tier %r nicht interpretierbar" % (tier,))
        if t not in p["allowed_tiers"]:
            return nein("tier_gesperrt",
                        "Tier %d (%s) ist bei Risk %d nicht erlaubt "
                        "(erlaubt: %s)"
                        % (t, TIER_NAMEN.get(t, "?"), r,
                           ", ".join(str(x) for x in p["allowed_tiers"])))

    # ── 4. Positionslimit ─────────────────────────────────────────────
    # VERDRAHTUNG 2026-09-27: wenn der Aufrufer seine gehaltenen Ticker
    # uebergibt, zaehlt der Controller Tier-3- und Diversifikations-Regeln
    # SELBST. Vorher musste das jeder Aufrufer richtig machen – und keiner
    # tat es, wodurch strategie.TIER_MAX_PENNY und TIER_MIN_VERSCHIEDEN
    # wirkungslos blieben.
    if positionen is not None:
        min_bestehend = max(min_bestehend, penny_positionen(positionen))
        # Der Aufrufer hat die Positionen benannt, also kennen wir die Zahl
        # auch – anzahl_positionen muss er nicht doppelt uebergeben.
        if anzahl_positionen is None:
            anzahl_positionen = len(list(positionen))
    if tier_anzahl is None and positionen is not None:
        tier_anzahl = tier_verschiedene(positionen)
    if anzahl_positionen is None:
        anzahl_positionen = 0

    try:
        n = int(anzahl_positionen)
    except (TypeError, ValueError):
        n = 0
    if n >= p["max_positions"]:
        return nein("positionslimit",
                    "Depot hat %d Positionen, Limit fuer Risk %d ist %d"
                    % (n, r, p["max_positions"]))

    # ── 5. Tier-Mix: hoechstens TIER_MAX_PENNY Penny-Positionen ───────
    if verlangt_penny_limit and strategie is not None and tier is not None:
        try:
            if int(tier) == 3 and min_bestehend >= strategie.TIER_MAX_PENNY:
                return nein("penny_limit",
                            "Depot haelt bereits %d Penny-Position(en) "
                            "(TIER_MAX_PENNY=%d)"
                            % (min_bestehend, strategie.TIER_MAX_PENNY))
        except (TypeError, ValueError):
            pass

    # ── 6. Score-Gate ─────────────────────────────────────────────────
    if score is not None and p["min_score"] > 0:
        try:
            if float(score) < p["min_score"]:
                return nein("score_zu_niedrig",
                            "Score %.1f < min_score %d fuer Risk %d"
                            % (float(score), p["min_score"], r))
        except (TypeError, ValueError):
            return nein("score_unbekannt", "Score %r nicht interpretierbar" % (score,))

    # ── 7. Bargeld und Betrag ─────────────────────────────────────────
    try:
        cash_v = float(cash or 0.0)
    except (TypeError, ValueError):
        return nein("cash_unbekannt", "Cash %r nicht interpretierbar" % (cash,))
    if cash_v <= 0:
        return nein("kein_cash", "Depot hat kein Cash mehr (%.2f)" % cash_v)

    # Gewuenschter Betrag: entweder explizit oder der Maximalbetrag
    hebel = False
    if tier is not None:
        try:
            hebel = int(tier) in HEBEL_TIERS
        except (TypeError, ValueError):
            hebel = False
    if strategie is not None and ticker is not None:
        try:
            hebel = hebel or strategie.ist_hebel_etf(ticker, tier)
        except Exception:
            pass

    if betrag is None:
        betrag_v = max_betrag(cash_v, r, tier=tier, vol_ratio=vol_ratio, hebel=hebel)
    else:
        try:
            betrag_v = float(betrag)
        except (TypeError, ValueError):
            return nein("betrag_unbekannt", "Betrag %r nicht interpretierbar" % (betrag,))

    if betrag_v <= 0:
        grund = "Cash-Boden laesst keinen Kauf zu" if cash_v > 0 else "kein Cash"
        if vol_ratio is not None and strategie is not None:
            if strategie.volumen_pos_size(vol_ratio) <= 0:
                grund = ("Volumen zu illiquide (vol_ratio=%s < VOL_ILLIQUID=%s)"
                         % (vol_ratio, strategie.VOL_ILLIQUID))
        return nein("kein_betrag", "%s (Cash %.2f, Risk %d)" % (grund, cash_v, r))

    # ── 8. HARTE OBERGRENZUNG: Betrag darf nie das Cash oder die
    #       Positionsgroesse ueberschreiten. Genau hier lief Befund 1
    #       (Ausweichkauf mit 100% des Depot-Cash) und Befund 4
    #       (faktor "voll" = 100% des Cash) vorher aus dem Ruder. ─────
    limit = max_betrag(cash_v, r, tier=tier, vol_ratio=vol_ratio, hebel=hebel)
    # Toleranz: 1 Cent. Kaufbetraege entstehen aus gerundeten Stueckzahlen und
    # Fliesskomma-Arithmetik; ein Block wegen 0.0000002 EUR waere grundlos.
    # Eine echte Limitverletzung ist immer groesser als 1 Cent.
    if betrag_v > limit + 0.01:
        werte = []
        if strategie is not None and hebel:
            werte.append("Hebel-ETF-Max %.0f%%" % (strategie.HEBEL_ETF_MAX_POS * 100))
        werte.append("position_size %.0f%%" % (p["position_size"] * 100))
        werte.append("Cash-Boden %.0f%%" % (p["cash_floor"] * 100))
        return nein("betrag_ueber_limit",
                    "Betrag %.2f > erlaubt %.2f fuer Risk %d (%s)"
                    % (betrag_v, limit, r, ", ".join(werte)))

    if betrag_v > cash_v + 1e-9:
        return nein("betrag_ueber_cash",
                    "Betrag %.2f > Cash %.2f" % (betrag_v, cash_v))

    # ── 9. Tier-Mix: mindestens TIER_MIN_VERSCHIEDEN verschiedene Tiers ─
    # Als Hinweis am Ergebnis, nicht als harter Block: ein Depot mit genau
    # EINER Position soll nicht dauerhaft blockiert werden. Die Regel
    # schlaegt dann durch, wenn bereits mehrere Positionen existieren und
    # der ZUKUNFTIGE Kauf die Tier-Anzahl nicht erhoehen wuerde.
    hinweis = ""
    if verlangt_tier_mix and strategie is not None:
        aktuelle_tiers = tier_anzahl if tier_anzahl is not None else 0
        if n > 0 and aktuelle_tiers < strategie.TIER_MIN_VERSCHIEDEN:
            hinweis = (" (Hinweis: Depot hat %d Tier(s), TIER_MIN_VERSCHIEDEN=%d "
                       "noch nicht erfuellt)" % (aktuelle_tiers,
                                                 strategie.TIER_MIN_VERSCHIEDEN))

    return PruefErgebnis(False, "ok: Risk %d, Betrag %.2f <= Limit %.2f%s"
                         % (r, betrag_v, limit, hinweis), "erlaubt", limit, p)


# ══════════════════════════════════════════════════════════════════════
# Hilfsfunktionen fuer die Trader-Module
# ══════════════════════════════════════════════════════════════════════

def _tier_von_ticker(ticker):
    """Tier eines Tickers, mit Fallback auf Tier 2 (wie engine.bewerte)."""
    try:
        # Lazy-Import: risk_profile importiert risk_controller am Dateiende,
        # ein Top-Level-Import wuerde einen Zyklus erzeugen.
        from risk_profile import TICKER_TO_TIER
        return int(TICKER_TO_TIER.get(ticker, 2))
    except Exception:
        return 2


def penny_positionen(positionen):
    """Zaehlt die gehaltenen Positionen im Tier 3 (Spekulativ/Penny).

    Wird fuer strategie.TIER_MAX_PENNY gebraucht. Die Aufrufstellen muessen
    das nicht selbst zaehlen – pruefe_und_bremse() erledigt es, sobald es
    die `positionen` bekommt. So kann keine Aufrufstelle die Penny-Regel
    versehentlich vergessen.
    """
    n = 0
    for t in (positionen or []):
        if _tier_von_ticker(t) == 3:
            n += 1
    return n


def tier_verschiedene(positionen):
    """Anzahl verschiedener Tiers im Depot (fuer TIER_MIN_VERSCHIEDEN)."""
    return len({_tier_von_ticker(t) for t in (positionen or [])})


def drawdown_pct_von(start_wert, aktuell_wert):
    """Drawdown in Prozent (>=0). Negativer Drawdown -> 0."""
    try:
        s = float(start_wert)
        a = float(aktuell_wert)
    except (TypeError, ValueError):
        return 0.0
    if s <= 0:
        return 0.0
    dd = (1.0 - (a / s)) * 100.0
    return round(dd if dd > 0 else 0.0, 2)


def depot_freigefroren(start_wert, aktuell_wert, risk):
    """True, wenn das Depot wegen Drawdown-Lock nicht mehr kaufen darf."""
    dd = drawdown_pct_von(start_wert, aktuell_wert)
    return dd >= params(risk)["max_drawdown"], dd


def _clamp_risk(risk):
    try:
        r = int(round(float(risk)))
    except (TypeError, ValueError):
        r = 50
    return max(RISK_MIN, min(RISK_MAX, r))


def _selbsttest():
    """Prueft die Kernzusagen des Moduls. Exit-Code 0 = alles gruen."""
    fehler = []

    # 1. Risk 0 und Risk 95 bekommen UNTERSCHIEDLICHE Tiers
    if allowed_tiers(0) == allowed_tiers(95):
        fehler.append("allowed_tiers(0) == allowed_tiers(95): %s" % allowed_tiers(0))
    if 4 in allowed_tiers(0) or 4 in allowed_tiers(20):
        fehler.append("Risk 0/20 darf Tier 4 (Hebel) nicht kaufen")
    if 4 not in allowed_tiers(95):
        fehler.append("Risk 95 muss Tier 4 (Hebel) erlauben")

    # 2. tier_bonus nicht ueberall 0
    b0, b95 = tier_bonus(0), tier_bonus(95)
    if all(v == 0 for v in b0.values()):
        fehler.append("tier_bonus(0) ist ueberall 0")
    if all(v == 0 for v in b95.values()):
        fehler.append("tier_bonus(95) ist ueberall 0")
    if b0 == b95:
        fehler.append("tier_bonus(0) == tier_bonus(95) -> keine Risikodifferenz")

    # 3. Cash-Boden: Depot kann nie zu 100% investiert sein
    for r in range(0, 100, 5):
        p = params(r)
        if p["cash_floor"] <= 0:
            fehler.append("Risk %d: cash_floor <= 0" % r)
        if p["max_positions"] * p["position_size"] > (1.0 - p["cash_floor"] + 1e-9):
            fehler.append("Risk %d: max_pos*pos_size %.3f > Investierbar %.3f"
                          % (r, p["max_positions"] * p["position_size"],
                             1.0 - p["cash_floor"]))

    # 4. Einstieg blockiert und liefert IMMER einen Grund
    res = pruefe_und_bremse(0, ticker="TQQQ", tier=4, preis=50.0, cash=1000.0)
    if not res.blockiert:
        fehler.append("pruefe_und_bremse hat TQQQ bei Risk 0 durchgelassen")
    if not res.reason:
        fehler.append("blockiertes Ergebnis ohne reason")
    res2 = pruefe_und_bremse(95, ticker="AAPL", tier=1, preis=200.0, cash=1000.0)
    if res2.blockiert:
        fehler.append("pruefe_und_bremse blockiert AAPL bei Risk 95: %s" % res2.reason)

    # 5. 100%-Betrag wird geklemmt
    res3 = pruefe_und_bremse(50, ticker="AAPL", tier=1, preis=100.0,
                             cash=1000.0, betrag=1000.0)
    if not res3.blockiert:
        fehler.append("100% des Cash wurden erlaubt")

    if fehler:
        print("risk_controller.py: SELBSTTEST FEHLGESCHLAGEN")
        for f in fehler:
            print("  - " + f)
        return 1
    print("risk_controller.py: Selbsttest OK "
          "(Risk 0 -> Tiers %s, Risk 95 -> Tiers %s)"
          % (allowed_tiers(0), allowed_tiers(95)))
    return 0


if __name__ == "__main__":
    print("Risk-Controller – Parameter je Risikostufe")
    print("%-5s %-4s %-5s %-5s %-5s %-5s %-6s %-8s %s"
          % ("risk", "tiers", "maxp", "pos%", "sl", "tp", "dd%", "cash%", "tier_bonus"))
    for r in (0, 20, 40, 60, 75, 95):
        p = params(r)
        print("%-5d %-4s %-5d %-5.0f %-5.3f %-5.3f %-6.1f %-8.0f %s"
              % (r, ",".join(str(t) for t in p["allowed_tiers"]),
                 p["max_positions"], p["position_size"] * 100,
                 p["stop_loss"], p["take_profit"], p["max_drawdown"],
                 p["cash_floor"] * 100, p["tier_bonus"]))
    raise SystemExit(_selbsttest())
