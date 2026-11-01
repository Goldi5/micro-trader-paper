#!/usr/bin/env python3
"""ETF-Universum – 30 ETFs mit Risiko-Rating 0-100 (5 Stufen).

Stufe 0:   0-20   Anleihen / Geldmarkt (SHY, IEF, TLT, BIL, AGG, BND, LQD, TIP, MUB, HYG)
Stufe 1:  21-40   Breite Markt-ETFs (SPY, VTI, VOO, IVV, VGK, EEM, IWM, DIA, VEA, VB)
Stufe 2:  41-60   Sektoren / Rohstoffe (GLD, SLV, XLE, XLF, XLV, XLI, XLK, XLU, XLP, XLY)
Stufe 3:  61-80   Themen-ETFs (QQQ, ARKK, IBB, SMH, XBI, TAN, BOTZ, ARKQ, CLOU, ICLN)
Stufe 4:  81-100  Gehebelt / Inverse (TQQQ, SPXL, SOXL, UPRO, SQQQ, SPXS, UVXY, TMF, FAS, FAZ)

Jeder ETF hat ein risk_score (0-100) + einen Sektor.
"""
from typing import Dict, List, Tuple

# 30 ETFs mit Rating 0-100 + Sektor
ETF_UNIVERSE: List[Dict] = [
    # ─── Stufe 0: Anleihen / Geldmarkt (0-20) ───
    {"ticker": "SHY",   "name": "1-3 Year Treasury Bond",       "risk_score": 5,   "sektor": "Anleihen"},
    {"ticker": "IEF",   "name": "7-10 Year Treasury Bond",      "risk_score": 10,  "sektor": "Anleihen"},
    {"ticker": "TLT",   "name": "20+ Year Treasury Bond",       "risk_score": 15,  "sektor": "Anleihen"},
    {"ticker": "BIL",   "name": "1-3 Month T-Bill",             "risk_score": 2,   "sektor": "Geldmarkt"},
    {"ticker": "AGG",   "name": "U.S. Aggregate Bond",          "risk_score": 8,   "sektor": "Anleihen"},
    {"ticker": "BND",   "name": "Total Bond Market",            "risk_score": 8,   "sektor": "Anleihen"},
    # ─── Stufe 1: Breite Markt-ETFs (21-40) ───
    {"ticker": "SPY",   "name": "S&P 500",                      "risk_score": 28,  "sektor": "Markt"},
    {"ticker": "VTI",   "name": "Total Stock Market",           "risk_score": 28,  "sektor": "Markt"},
    {"ticker": "URTH",  "name": "MSCI World (iShares)",         "risk_score": 30,  "sektor": "Markt"},
    {"ticker": "VGK",   "name": "FTSE Europe",                  "risk_score": 32,  "sektor": "Markt"},
    {"ticker": "EEM",   "name": "Emerging Markets",             "risk_score": 38,  "sektor": "Markt"},
    {"ticker": "IWM",   "name": "Russell 2000 (Small Cap)",     "risk_score": 42,  "sektor": "Markt"},
    {"ticker": "DIA",   "name": "Dow Jones Industrial",         "risk_score": 25,  "sektor": "Markt"},
    # ─── Stufe 2: Sektoren / Rohstoffe (41-60) ───
    {"ticker": "GLD",   "name": "Gold Trust",                   "risk_score": 42,  "sektor": "Rohstoffe"},
    {"ticker": "SLV",   "name": "Silver Trust",                 "risk_score": 48,  "sektor": "Rohstoffe"},
    {"ticker": "XLE",   "name": "Energy Select Sector",         "risk_score": 55,  "sektor": "Energie"},
    {"ticker": "XLF",   "name": "Financial Select Sector",      "risk_score": 50,  "sektor": "Finanzen"},
    {"ticker": "XLV",   "name": "Health Care Select Sector",    "risk_score": 45,  "sektor": "Gesundheit"},
    {"ticker": "USO",   "name": "United States Oil Fund",       "risk_score": 58,  "sektor": "Rohstoffe"},
    # ─── Stufe 3: Themen-ETFs (61-80) ───
    {"ticker": "QQQ",   "name": "NASDAQ-100 (Tech)",            "risk_score": 65,  "sektor": "Technologie"},
    {"ticker": "ARKK",  "name": "ARK Innovation",               "risk_score": 78,  "sektor": "Innovation"},
    {"ticker": "IBB",   "name": "Biotechnology",                "risk_score": 72,  "sektor": "Gesundheit"},
    {"ticker": "SMH",   "name": "Semiconductor",                "risk_score": 68,  "sektor": "Technologie"},
    {"ticker": "XBI",   "name": "S&P Biotech",                  "risk_score": 75,  "sektor": "Gesundheit"},
    {"ticker": "BOTZ",  "name": "Global Robotics & AI",         "risk_score": 70,  "sektor": "Technologie"},
    # ─── Stufe 4: Gehebelt / Inverse (81-100) ───
    {"ticker": "TQQQ",  "name": "3x Bull NASDAQ-100",           "risk_score": 95,  "sektor": "Gehebelt"},
    {"ticker": "SPXL",  "name": "3x Bull S&P 500",             "risk_score": 90,  "sektor": "Gehebelt"},
    {"ticker": "SOXL",  "name": "3x Bull Semiconductor",       "risk_score": 98,  "sektor": "Gehebelt"},
    {"ticker": "SQQQ",  "name": "3x Bear NASDAQ-100",           "risk_score": 88,  "sektor": "Inverse"},
    {"ticker": "SPXS",  "name": "3x Bear S&P 500",             "risk_score": 85,  "sektor": "Inverse"},
    {"ticker": "UVXY",  "name": "1.5x Short VIX Futures",      "risk_score": 100, "sektor": "Volatilität"},
]

# Lookup-Maps
TICKER_TO_ETF = {e["ticker"]: e for e in ETF_UNIVERSE}
TICKER_TO_RISK = {e["ticker"]: e["risk_score"] for e in ETF_UNIVERSE}
ETF_TICKERS = list(TICKER_TO_ETF.keys())

# Risiko-Stufe aus Score ableiten (0-4)
def risk_stufe(score: int) -> int:
    if score <= 20:  return 0
    elif score <= 40: return 1
    elif score <= 60: return 2
    elif score <= 80: return 3
    else:             return 4

# Depot-Typ: "etf"
DEPOT_TYP = "etf"

if __name__ == "__main__":
    print(f"ETF-Universum: {len(ETF_UNIVERSE)} ETFs")
    for stufe in range(5):
        etfs = [e for e in ETF_UNIVERSE if risk_stufe(e["risk_score"]) == stufe]
        print(f"  Stufe {stufe} (Score {stufe*20}-{stufe*20+20}): {', '.join(e['ticker'] for e in etfs)}")
