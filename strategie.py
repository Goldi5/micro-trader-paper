#!/usr/bin/env python3
"""
strategie.py - ZENTRALE STRATEGIE-CONFIG (Single Source of Truth)
===============================================================

Alle weichen Bewertungsregeln des Micro-Traders in EINER Datei.
engine.py (Aktien), etf_trader.py (ETF), spec_trader.py (Spec) und
ki_decisions.py (KI-Prompt) lesen hieraus - keine hartcodierten
Regelwerte mehr in den Modulen.

Regeln (v2.20.0):
- PENNY_PENALTY: Aktien <$5 abwerten, $5-30 bevorzugen, >$30 neutral
- VOLUMEN_DAEMPFER: Volumen ist Dämpfer, kein Kauf-Stopp
- HEBEL_ETF: 3x-Produkte erlaubt, aber kleine Position
- TIER_MIX: max 1 Penny-Tier pro Depot, mind. 2 verschiedene Tiers
"""

# ─── Penny-Penalty (Preis-Scoring) ───────────────────────────────
# Aktien/ETF mit Preis < PENNY_MAX bekommen Abzug, $5-30 bevorzugt.
PENNY_MAX = 5.0          # unter diesem Preis: Penalty
SMALLCAP_MAX = 30.0      # bis hier: bevorzugt (Diversifikation)
PENNY_PENALTY = -10      # Score-Abzug für < PENNY_MAX
SMALLCAP_BONUS = 8       # Score-Bonus für PENNY_MAX..SMALLCAP_MAX
EXPENSIVE_BONUS = 3      # Score-Bonus für > SMALLCAP_MAX (neutral-leicht positiv)
TOO_EXPENSIVE_MALUS = -25  # Score-Abzug wenn preis > budget (kaum Chance)

def preis_score(preis, budget):
    """Einheitliche Preis-Bewertung für Aktien + ETF (ersetzt engine.bewerte + etf_bewerte Bias)."""
    if preis is None or preis <= 0:
        return 0
    if preis < PENNY_MAX:
        return PENNY_PENALTY
    elif preis <= SMALLCAP_MAX:
        return SMALLCAP_BONUS
    else:
        # >30: leicht positiv, aber nicht mehr als Small-Cap
        return EXPENSIVE_BONUS
    # Hinweis: "zu teuer für Budget" wird vom Aufrufer geprüft (preis > budget → TOO_EXPENSIVE_MALUS)

# ─── Volumen-Dämpfer (kein Kauf-Stopp) ──────────────────────────
VOL_DAEMPFER_1 = 0.30     # vol_ratio < 0.30 → nur kleinere Position (SATZ_1)
VOL_DAEMPFER_2 = 0.15     # vol_ratio < 0.15 → noch kleinere Position (SATZ_2)
VOL_ILLIQUID = 0.08       # vol_ratio < 0.08 → Verzicht (illiquide)
VOL_POS_SIZE_1 = 0.70     # 70% Position bei < VOL_DAEMPFER_1
VOL_POS_SIZE_2 = 0.40     # 40% Position bei < VOL_DAEMPFER_2

def volumen_pos_size(vol_ratio):
    """Gibt den Positions-Faktor zurück (1.0 = voll, <1 = gedämpft, 0 = Verzicht)."""
    if vol_ratio is None:
        return 1.0
    if vol_ratio < VOL_ILLIQUID:
        return 0.0       # illiquide: Verzicht
    elif vol_ratio < VOL_DAEMPFER_2:
        return VOL_POS_SIZE_2
    elif vol_ratio < VOL_DAEMPFER_1:
        return VOL_POS_SIZE_1
    return 1.0            # normales Volumen: volle Position

# ─── Hebel-ETF ───────────────────────────────────────────────────
HEBEL_ETF_ERLAUBT = True          # 3x-Produkte dürfen gekauft werden
HEBEL_ETF_MAX_POS = 0.30          # max 30% des Depot-Cash (Slippage/Vola)
HEBEL_TIERS = {3, 6}              # Tier 3 spekulativ, Tier 6 Hebel/Inverse
                                     # TIER-SEMANTIK 2026-09-27: vorher {3, 4}.
                                     # Tier 4 ist jetzt "ETF breit" (SPY, GLD,
                                     # XLU, ...), und stand hier als gehebelt -
                                     # SPY wurde dadurch wie ein 3x-Produkt
                                     # behandelt und auf 30 % statt 34 %
                                     # gedeckelt.
HEBEL_ETF_LISTE = [               # bekannte 3x-Produkte (für KI-Prompt + Filter)
    "TQQQ", "SQQQ", "UVXY", "VXX", "VIXY", "SOXS", "SPXS", "JDST", "JNUG",
    "FNGU", "BOIL", "UCO", "SCO", "NRGU", "FAZ", "SPXU", "SVXY", "LABU",
    "UPRO", "TNA", "FAS", "SOXL", "TECL", "UDOW", "QLD", "SSO", "ROM",
    "DDM", "MVV", "UWM", "TYD", "UVIX", "MSTX", "CONL", "BITX", "ETHU", "MSTR2",
]

def ist_hebel_etf(ticker, tier=None):
    """Prüft ob Ticker ein Hebel-ETF ist (Tier 3/4 oder in Liste)."""
    if ticker in HEBEL_ETF_LISTE:
        return True
    if tier in HEBEL_TIERS:
        return True
    return False

# ─── Tier-Mix (Diversifikation) ──────────────────────────────────
TIER_MAX_PENNY = 1         # max 1 Position aus Tier 3 (Penny) pro Depot
TIER_MIN_VERSCHIEDEN = 2    # mind. 2 verschiedene Tiers pro Depot
TIER_NAMEN = {0: "Defensiv", 1: "Large-Cap", 2: "Growth", 3: "Spekulativ", 4: "ETF/Hebel"}

# ─── KI-Prompt Bausteine (für ki_decisions.py) ──────────────────
STRATEGIE_HINWEISE = f"""STRATEGIE-HINWEISE (Diversifikation, keine harten Verbote, aus strategie.py):
- Bevorzuge MEHRERE KLEINE Positionen statt weniger teurer: bei verfügbarem Cash
  sind 3-5 Positionen à <$30 sinnvoller als 1-2 große Klumpen.
- VOLUMEN ist ein DÄMPFER, kein Kauf-Stopp: bei vol_ratio <{VOL_DAEMPFER_1:.2f}x nur kleinere
  Position ({int(VOL_POS_SIZE_1*100)}%) kaufen, bei vol_ratio <{VOL_DAEMPFER_2:.2f}x noch {int(VOL_POS_SIZE_2*100)}%.
  Erst bei vol_ratio <{VOL_ILLIQUID:.2f}x (sehr illiquide) ganz auf KAUF verzichten. Mehr Käufe = mehr Lern-Signal.
- HEBEL-ETFs (3x, z.B. {', '.join(HEBEL_ETF_LISTE[:8])}...) duerfen gekauft werden, aber nur mit
  KLEINER Position (max {int(HEBEL_ETF_MAX_POS*100)}% des Depot-Cash) wegen Slippage/Vola.
  Kein generelles "halten" mehr - das Lernen braucht Fehler.
- DIVERSIFIKATION pro Depot: max. {TIER_MAX_PENNY} Position aus Tier 3 (Penny), mische mind.
  {TIER_MIN_VERSCHIEDEN} verschiedene Tiers (Bluechip/Mid/Grow/Penny/ETF). Vermeide "alles Pennystocks"
  oder "alles Bluechips"."""

if __name__ == "__main__":
    # Selbsttest
    assert preis_score(2.0, 100) == PENNY_PENALTY
    assert preis_score(15.0, 100) == SMALLCAP_BONUS
    assert preis_score(75.0, 100) == EXPENSIVE_BONUS
    assert volumen_pos_size(0.05) == 0.0
    assert volumen_pos_size(0.10) == VOL_POS_SIZE_2
    assert volumen_pos_size(0.50) == 1.0
    assert ist_hebel_etf("TQQQ") == True
    assert ist_hebel_etf("AAPL") == False
    print("strategie.py: Selbsttest OK")
