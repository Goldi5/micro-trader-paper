"""news_ticker_map.py — Phase 4: Zentrale Firma→Ticker Mapping-Tabelle.

Wird von news_monitor (Ticker-Erkennung) + spaeter news_evaluator (Trading-Kontext)
genutzt. Nicht-boersennotierte Emittenten (Bloomberg, Fed) -> None (nur Kontext).

Aufruf: from news_ticker_map import find_tickers, FIRMENNAME_MAP
"""

# Firma (Gross-/Kleinschreibung egal) -> Ticker
# Erweiterbar: einfach Eintraege ergaenzen.
FIRMENNAME_MAP = {
    "nvidia": "NVDA",
    "apple": "AAPL",
    "tesla": "TSLA",
    "microsoft": "MSFT",
    "meta": "META",
    "amazon": "AMZN",
    "google": "GOOGL",
    "alphabet": "GOOGL",
    "amd": "AMD",
    "jp morgan": "JPM",
    "jpmorgan": "JPM",
    "bank of america": "BAC",
    "coinbase": "COIN",
    "gamestop": "GME",
    "palantir": "PLTR",
    "lucid": "LCID",
    "rivian": "RIVN",
    "ford": "F",
    "general motors": "GM",
    "robinhood": "HOOD",
    "sofi": "SOFI",
    "proshares": None,       # TQQQ etc. sind Produkte, kein Einzel-Ticker
    "citadel": None,
    "federal reserve": None,
    "fed": None,
    "bloomberg": None,
    "sec": None,
}

# Explizite Ticker (direkt im Text) -> bestaetigt
BEKANNTE_TICKER = {
    "NVDA", "AAPL", "TSLA", "MSFT", "META", "AMZN", "GOOGL", "AMD", "JPM",
    "BAC", "COIN", "GME", "PLTR", "LCID", "RIVN", "F", "GM", "HOOD", "SOFI",
    "TQQQ", "MARA", "SNAP", "PATH", "SOUN", "BBAI", "BB", "CRSP", "MRNA",
    "FNGU", "NRGU", "TNA", "QS",
}


def find_tickers(text):
    """Findet Ticker in einem Headline-Text.
    Prueft: (1) explizite Ticker (AAPL, $TSLA), (2) Firmennamen-Mapping.
    Returns: Liste eindeutiger Ticker (ohne None-Eintraege)."""
    if not text:
        return []
    t = text.lower()
    found = set()
    # (1) Explizite Ticker
    for tk in BEKANNTE_TICKER:
        if tk in t or f"${tk.lower()}" in t:
            found.add(tk)
    # (2) Firmenname-Mapping
    for firma, tk in FIRMENNAME_MAP.items():
        if firma in t and tk:
            found.add(tk)
    return sorted(found)


if __name__ == "__main__":
    for probe in ["Tesla stock rallies", "NVIDIA beats estimates", "Fed holds rates",
                  "Apple $AAPL neues Produkt", "Citadel warnt vor Leverage"]:
        print(f"{probe!r:45} -> {find_tickers(probe)}")
