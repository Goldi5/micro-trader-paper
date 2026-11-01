#!/usr/bin/env python3
"""KI-Kontext-Modul: reichert Entscheidungs-Prompts mit System-Wissen an.

Liefert:
1. ticker_konzentration(ticker)  — in wie vielen Depots liegt der Ticker (Diversifikation)
2. fundamentals(ticker)          — P/E, EPS, Marktkapitalisierung, Marge (yfinance info, 24h-Cache)
3. selbst_statistik()            — Trefferquote/Ø-Lerneffekt der KI (Selbst-Bewusstsein)
4. kontext_block(ticker)         — fertiger Prompt-Text aus allem

Kein Crash bei Fehlern — alle Funktionen liefern sichere Defaults.
"""

import json, os
from datetime import datetime, timedelta


def news_fuer_ticker(ticker, max_age_h=24, max_items=3):
    """Holt bewertete News für einen Ticker aus ki_log.json (letzte N Stunden).

    Liefert bis zu max_items News mit score, topic, reason für den Prompt.
    """
    ticker = (ticker or "").upper()
    if not ticker:
        return []
    try:
        with open(os.path.join(BASE, "ki_log.json"), encoding="utf-8") as f:
            log = json.load(f)
        cutoff = datetime.now() - timedelta(hours=max_age_h)
        news = []
        for e in log:
            if e.get("typ") != "news":
                continue
            try:
                z = datetime.fromisoformat(e.get("zeit", ""))
                if z < cutoff:
                    continue
            except Exception:
                continue
            # Prüfen ob Ticker in news.tickers steht
            if ticker in [t.upper() for t in e.get("tickers", [])]:
                news.append({
                    "title": e.get("title", "")[:120],
                    "score": e.get("score", 50),
                    "topics": e.get("topics", []),
                    "reason": e.get("reason", "")[:100],
                })
                if len(news) >= max_items:
                    break
        return news
    except Exception:
        return []

BASE = os.path.dirname(os.path.abspath(__file__))
FUND_CACHE = os.path.join(BASE, "fundamentals_cache.json")
FUND_TTL = 24 * 3600  # 24h


# ─── 1. Konzentration (Diversifikation) ─────────────────────
def ticker_konzentration(ticker):
    """Zählt, in wie vielen Depots (Aktien + ETF + Spec) der Ticker als
    offene Position (shares > 0) liegt. → verhindert Klumpenrisiko (z.B. DOMO in 8 Depots)."""
    ticker = (ticker or "").upper()
    if not ticker:
        return 0
    depots = 0
    try:
        # Aktien-Depots: depot_XXX.json
        for fn in os.listdir(BASE):
            if fn.startswith("depot_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(BASE, fn), encoding="utf-8") as f:
                        d = json.load(f)
                    pos = d.get("positions", {})
                    if pos.get(ticker, {}).get("shares", 0) > 0:
                        depots += 1
                except Exception:
                    pass
        # ETF-Depots: etf_XXX.json
        for fn in os.listdir(BASE):
            if fn.startswith("etf_") and fn.endswith(".json"):
                try:
                    with open(os.path.join(BASE, fn), encoding="utf-8") as f:
                        d = json.load(f)
                    pos = d.get("positions", {})
                    if pos.get(ticker, {}).get("shares", 0) > 0:
                        depots += 1
                except Exception:
                    pass
        # Spec-Depots: spec_depots/TICKER.json
        spec_dir = os.path.join(BASE, "spec_depots")
        if os.path.isdir(spec_dir):
            for fn in os.listdir(spec_dir):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(spec_dir, fn), encoding="utf-8") as f:
                        d = json.load(f)
                    if d.get("ticker", "").upper() == ticker and d.get("shares", 0) > 0:
                        depots += 1
                except Exception:
                    pass
    except Exception:
        pass
    return depots


# ─── 2. Fundamentaldaten (24h-Cache) ─────────────────────────
def _lade_fund_cache():
    try:
        with open(FUND_CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _speichere_fund_cache(cache):
    try:
        with open(FUND_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def fundamentals(ticker):
    """P/E, EPS, Marktkapitalisierung, Gewinnmarge via yfinance info (24h-Cache)."""
    ticker = (ticker or "").upper()
    if not ticker:
        return {}
    cache = _lade_fund_cache()
    eintrag = cache.get(ticker)
    if eintrag:
        try:
            if (datetime.now() - datetime.fromisoformat(eintrag["zeit"])) < timedelta(seconds=FUND_TTL):
                return eintrag.get("daten", {})
        except Exception:
            pass
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        pe = info.get("trailingPE") or info.get("forwardPE")
        daten = {
            "pe": round(float(pe), 1) if pe else None,
            "eps": round(float(info.get("trailingEps") or 0), 2) if info.get("trailingEps") else None,
            "mcap": float(info.get("marketCap") or 0) or None,
            "marge": round(float(info.get("profitMargins") or 0) * 100, 1) if info.get("profitMargins") else None,
        }
        if not all(v is None for v in daten.values()):
            cache[ticker] = {"zeit": datetime.now().isoformat(), "daten": daten}
            _speichere_fund_cache(cache)
            return daten
    except Exception:
        pass
    return {}


def _fmt_mcap(mcap):
    if not mcap:
        return "?"
    if mcap >= 1e12:
        return f"{mcap/1e12:.1f} Bio$"
    if mcap >= 1e9:
        return f"{mcap/1e9:.1f} Mrd$"
    return f"{mcap/1e6:.0f} Mio$"


# ─── 3. Selbst-Statistik (KI-Ehrlichkeit) ────────────────────
def selbst_statistik(max_age_h=24):
    """Trefferquote + Ø-Lerneffekt der KI aus ki_log (letzte N Stunden)."""
    try:
        with open(os.path.join(BASE, "ki_log.json"), encoding="utf-8") as f:
            log = json.load(f)
        cutoff = datetime.now() - timedelta(hours=max_age_h)
        werte = []
        for e in log:
            if e.get("typ") != "learned":
                continue
            le = e.get("lerneffekt")
            if not isinstance(le, (int, float)):
                continue
            try:
                z = datetime.fromisoformat(e.get("zeit", ""))
                if z < cutoff:
                    continue
            except Exception:
                continue
            werte.append(le)
        if not werte:
            return {"anzahl": 0, "trefferquote": None, "avg": None}
        pos = sum(1 for w in werte if w >= 1)
        return {
            "anzahl": len(werte),
            "trefferquote": round(pos / len(werte) * 100, 1),
            "avg": round(sum(werte) / len(werte), 2),
        }
    except Exception:
        return {"anzahl": 0, "trefferquote": None, "avg": None}


# ─── 4. Fertiger Prompt-Block ────────────────────────────────
def kontext_block(ticker, sektor=""):
    """Baut den Zusatz-Kontext für einen Ticker (Konzentration + Fundamentals + News)."""
    ticker = (ticker or "").upper()
    if not ticker:
        return ""
    teile = []

    # Konzentration
    n = ticker_konzentration(ticker)
    if n >= 2:
        warn = "⚠" if n >= 3 else "·"
        teile.append(f"{warn} BEREITS IN {n} DEPOTS: Klumpenrisiko — bei n≥4 nicht weiter aufstocken")

    # Sektor
    if sektor:
        teile.append(f"SEKTOR: {sektor}")

    # Fundamentals
    fund = fundamentals(ticker)
    if fund:
        felder = []
        if fund.get("pe") is not None:
            felder.append(f"P/E {fund['pe']}")
        if fund.get("eps") is not None:
            felder.append(f"EPS ${fund['eps']}")
        if fund.get("mcap"):
            felder.append(f"Marktkap {_fmt_mcap(fund['mcap'])}")
        if fund.get("marge") is not None:
            felder.append(f"Marge {fund['marge']}%")
        if felder:
            teile.append("FUNDAMENTALS: " + " | ".join(felder))

    # 📰 News (bewertete, letzte 24h)
    news = news_fuer_ticker(ticker, max_age_h=24, max_items=2)
    if news:
        for nw in news:
            score = nw.get("score", 50)
            stern = "⭐⭐⭐" if score >= 70 else ("⭐⭐" if score >= 45 else ("⭐" if score >= 20 else ""))
            topics = ", ".join(nw.get("topics", [])) or "sonstiges"
            reason = nw.get("reason", "")
            teile.append(f"NEWS {stern} ({topics}): \"{nw['title'][:80]}\" — {reason}")

    # 📈 Multi-Timeframe (1h + 15min Momentum) — P3
    mtf = multi_timeframe(ticker)
    if mtf:
        teile.append(mtf)

    # 🌐 Phase 5 (S3.6): Marktregime (Bull/Bear/Seitwärts)
    try:
        from boersen import markt_regime, regime_label
        reg = markt_regime()
        if reg != "unbekannt":
            teile.append(f"MARKTREGIME: {regime_label(reg)} (S&P 500 vs. 200-Tage-Linie)")
    except Exception:
        pass

    return "\n".join(teile)


def multi_timeframe(ticker):
    """P3: Kurzfristiges Momentum (1h + 15min) für besseres Timing.

    Liefert Text wie 'MOMENTUM: 1h +1.2% (Aufwärts) | 15min -0.3% (Schwäche)'
    oder '' bei Fehler. Nutzt yfinance (kein Extra-API-Call bei aktivem Markt).
    """
    ticker = (ticker or "").upper()
    if not ticker:
        return ""
    try:
        import yfinance as yf
        out = []
        # 1h-Trend: letzte 2 Stunden
        h1 = yf.Ticker(ticker).history(period="2d", interval="1h")
        if h1 is not None and len(h1) >= 3:
            c0, c1 = h1["Close"].iloc[-3], h1["Close"].iloc[-1]
            ch = (c1 / c0 - 1) * 100
            richt = "Aufwärts" if ch > 0.3 else ("Abwärts" if ch < -0.3 else "Seitwärts")
            out.append(f"1h {ch:+.1f}% ({richt})")
        # 15min-Momentum
        m15 = yf.Ticker(ticker).history(period="1d", interval="15m")
        if m15 is not None and len(m15) >= 4:
            c0, c1 = m15["Close"].iloc[-4], m15["Close"].iloc[-1]
            ch = (c1 / c0 - 1) * 100
            richt = "Stärke" if ch > 0.2 else ("Schwäche" if ch < -0.2 else "neutral")
            out.append(f"15min {ch:+.1f}% ({richt})")
        if out:
            return "MOMENTUM (Kurzfristig): " + " | ".join(out)
    except Exception:
        pass
    return ""


# 01.11.2026: Die def-Zeile fehlte seit dem ersten Commit - der Rumpf hing
# als toter Code hinter dem return der Momentum-Funktion. Folge: Der Import
# "from ki_kontext import kontext_block, selbst_statistik_text" in
# ki_decisions.py scheiterte, und das except dort verwarf DEN GANZEN
# Kontext-Block (Konzentration, Sektor, Fundamentals) im KI-Prompt.
def selbst_statistik_text(max_age_h=24):
    """Prompt-Text: Wie gut lag die KI zuletzt? (Selbst-Bewusstsein-Kalibrierung)."""
    st = selbst_statistik(max_age_h)
    if st["anzahl"] < 5:
        return ""
    q = st["trefferquote"]
    if q is None:
        return ""
    einschaetzung = (
        "GUT" if q >= 50 else
        "MITTEL" if q >= 30 else
        "SCHWACH — sei vorsichtiger und vertraue nicht jedem Signal"
    )
    return (f"DEINE LETZTEN {st['anzahl']} ENTSCHEIDUNGEN: {q:.0f}% richtig, "
            f"Ø-Lerneffekt {st['avg']:+.2f} → Qualität: {einschaetzung}. "
            f"Passe dein Risiko daran an.")


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "DOMO"
    print(f"Konzentration {t}: {ticker_konzentration(t)} Depots")
    print(f"Fundamentals {t}: {fundamentals(t)}")
    print(f"Selbst-Statistik: {selbst_statistik_text()}")
    print("--- Kontext-Block ---")
    print(kontext_block(t) or "(leer)")
