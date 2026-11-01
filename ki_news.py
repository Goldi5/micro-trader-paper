"""KI-News-Analyse — sammelt News, bewertet sie per KI (zentrale Fallback-Kette), speichert in ki_log.json.

Nutzt ki_provider.call_ki() für konsistente Provider-Fallback (OpenAI→DeepSeek→Nous→OpenRouter).
Läuft per Cron (alle 2h) oder manuell.
"""
import json
import os
import time
from datetime import datetime, timedelta
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
NEWS_CACHE = os.path.join(BASE, "news_cache.json")
KI_LOG = os.path.join(BASE, "ki_log.json")

# RSS-Feeds (kein API-Key nötig)
FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://finance.yahoo.com/news/rssindex",
    "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headlines",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",
]

KEYWORDS = {
    "zinsen": ["interest rate", "fed", "federal reserve", "rate hike", "rate cut", "zins", "ezb"],
    "earnings": ["earnings", "quarterly results", "gewinn", "results", "eps"],
    "m&a": ["merger", "acquisition", "übernahme", "buyout", "takeover", "fusion"],
    "regulation": ["regulation", "sec", "regulatory", "regulierung", "klage", "lawsuit", "kartell"],
    "rezession": ["recession", "recession fears", "wirtschaftskrise", "recession warning"],
    "inflation": ["inflation", "cpi", "consumer price", "inflation data", "pce"],
    "tech": ["tech", "technology", "semiconductor", "ai", "chip", "künstliche intelligenz", "kqi"],
    "energy": ["oil", "crude", "energy", "gas", "öl", "energie", "wti", "brent"],
    "markt": ["market", "stock market", "dow", "s&p", "nasdaq", "index", "dax"],
    "geopolitik": ["war", "conflict", "trade war", "tariff", "zoll", "sanktion", "sanction", "china", "usa"],
    "krypto": ["bitcoin", "crypto", "blockchain", "ethereum", "krypto", "btc", "eth"],
}

# Blacklist: Offensichtlich irrelevante Themen (kein Trading-Bezug)
# → werden VOR der KI-Bewertung aussortiert (spart KI-Calls)
IRRELEVANT_KEYWORDS = [
    "celebrity", "promi", "royal", "royals", "kardashian", "trump trial", "election 2024",
    "election 2025", "election 2026", "sport", "olymp", "world cup", "fifa", "nba", "nfl",
    "entertainment", "movie", "film", "tv show", "netflix original", "music", "album",
    "fashion", "lifestyle", "recipe", "cooking", "travel", "vacation", "weather forecast",
    "wetter", "horoskop", "astrology", "health tip", "diet", "weight loss", "dating",
    "restaurant", "food review", "game review", "video game", "gaming", "xbox", "playstation",
    "obituary", "wedding", "birthday", "festival", "concert", "tour",
]

# Themen die einen Artikel NICHT relevant machen (auch wenn 1 Keyword matcht)
IRRELEVANT_CONTEXT = [
    "wikipedia", "wiki", "how to", "tutorial", "opinion", "kommentar", "gastbeitrag",
    "sponsored", "anzeige", "werbung", "press release", "pressemitteilung",
]


def ist_irrelevant(title):
    """Heuristische Vorfilterung: True wenn Headline offensichtlich irrelevant für Trading."""
    t = (title or "").lower()
    # Blacklist-Hits (Wort-genau, nicht Substring) → irrelevant
    import re
    words = set(re.findall(r"[a-z0-9]+", t))
    for kw in IRRELEVANT_KEYWORDS:
        # Exakte Wort-Phrasen oder Teil-Wort-Match (für "royals", "kardashian" etc.)
        if " " in kw:
            if kw in t:
                return True, f"Blacklist: {kw}"
        else:
            if kw in words:
                return True, f"Blacklist: {kw}"
    # Rein unterhaltungsbezogene Kontexte
    for kw in IRRELEVANT_CONTEXT:
        if kw in t:
            return True, f"Kontext: {kw}"
    # Zu kurz oder reine Clickbait-Muster
    if len(t.split()) < 4:
        return True, "zu kurz"
    return False, None


def classify_headline(title):
    """Klassifiziert eine Headline nach relevanten Themen."""
    title_lower = title.lower()
    matches = []
    for category, kws in KEYWORDS.items():
        for kw in kws:
            if kw in title_lower:
                matches.append(category)
                break
    return matches
KNOWN_TICKERS = [
    "AAPL", "MSFT", "TSLA", "NVDA", "AMD", "META", "AMZN", "GOOGL", "GOOG",
    "JPM", "BAC", "COIN", "GME", "PLTR", "LCID", "RIVN", "F", "GM",
    "HOOD", "SOFI", "TQQQ", "MARA", "RIOT", "MSTR", "BITO", "IBIT",
    "SPY", "QQQ", "VTI", "DIA", "IWM", "ARKK", "SMH", "SOXL", "TQQQ",
    "UVXY", "VXX", "SQQQ", "SPXS", "LABU", "LABD", "FAS", "FAZ",
    "NFLX", "CRM", "ADBE", "INTC", "QCOM", "AVGO", "TXN", "MU",
    "SHOP", "ROKU", "SNAP", "PINS", "UBER", "LYFT", "ABNB", "DASH",
]


def fetch_rss(url, timeout=10):
    """Holt einen RSS-Feed und gibt Headlines zurück."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pubdate = item.findtext("pubDate", "")
            if title:
                items.append({"title": title.strip(), "link": link, "date": pubdate})
        return items
    except Exception:
        return []



def find_tickers(title):
    """Findet Ticker-Symbole im Titel."""
    found = []
    title_upper = title.upper()
    for ticker in KNOWN_TICKERS:
        if ticker in title_upper or f"${ticker}" in title_upper:
            found.append(ticker)
    return found


def update_news_cache(max_items_per_feed=15):
    """Holt aktuelle News, klassifiziert, sucht Ticker, speichert in Cache."""
    alle = []
    for url in FEEDS:
        items = fetch_rss(url)
        if items:
            print(f"  ✅ {len(items)} von {url.split('/')[2]}")
        alle.extend(items[:max_items_per_feed])
        time.sleep(0.5)

    relevant = []
    irrel_anz = 0
    for item in alle:
        # ── VORFILTER: offensichtlich irrelevante News aussortieren ──
        irr, grund = ist_irrelevant(item["title"])
        if irr:
            irrel_anz += 1
            continue
        cats = classify_headline(item["title"])
        tickers = find_tickers(item["title"])
        if cats or tickers:
            relevant.append({**item, "topics": cats, "tickers": tickers})

    data = {
        "zeit": datetime.now().isoformat(),
        "total": len(alle),
        "relevant": len(relevant),
        "irrelevant": irrel_anz,
        "headlines": relevant[:50] if relevant else [{"title": "Keine relevanten News", "topics": [], "tickers": []}],
    }
    with open(NEWS_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n  📰 {len(alle)} Headlines gesammelt, {len(relevant)} relevant")
    for h in relevant[:5]:
        tkr = f" [{', '.join(h['tickers'])}]" if h['tickers'] else ""
        print(f"    • {h['title'][:100]}{tkr}")
    return relevant


def lade_news():
    if not os.path.exists(NEWS_CACHE):
        return []
    with open(NEWS_CACHE, encoding="utf-8") as f:
        return json.load(f).get("headlines", [])


def lade_ki_log():
    if not os.path.exists(KI_LOG):
        return []
    with open(KI_LOG, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def bereits_bewertet_titel(ki_log):
    return {e.get("title", "").strip().lower() for e in ki_log if e.get("typ") == "news"}


def letzte_news_evaluierung(ki_log):
    zeiten = []
    for e in ki_log:
        if e.get("typ") == "news":
            z = e.get("zeit", "")
            if z:
                try:
                    zeiten.append(datetime.fromisoformat(z))
                except ValueError:
                    pass
    return max(zeiten) if zeiten else None


STERN_TOPICS = ["zinsen", "earnings", "m&a", "regulation", "rezession", "inflation",
                "tech", "energy", "markt", "geopolitik", "krypto", "sonstiges"]


def build_news_prompt(headlines):
    """Baut den KI-Prompt für News-Bewertung."""
    prompt = (
        "Du bewertest Börsen-News für ein Paper-Trading-System. "
        "Gib ein JSON-Array zurück:\n\n"
        "[\n"
        '  {"title": "Headline", "score": 0-100, "topics": ["zinsen","tech","earnings",\n'
        '   "regulation","energie","markt","geopolitik","krypto","sonstiges"],\n'
        '   "tickers": ["AAPL"], "reason": "kurzer Grund"},\n'
        "  ...\n"
        "]\n\n"
        "Score = Relevanz für Aktien-Trading (0=unwichtig, 100=sehr relevant).\n"
        "Wähle 1-2 passende topics aus der Liste. Nenne Ticker wenn erkennbar.\n"
        "Antworte NUR mit dem JSON-Array.\n\n"
        "Headlines:\n"
    )
    for h in headlines:
        prompt += f"- {h.get('title', '?')}\n"
    return prompt


def parse_ki_response(raus, headlines):
    """Parst KI-Antwort zu Bewertungs-Liste."""
    try:
        start = raus.find("[")
        end = raus.rfind("]") + 1
        raus = raus[start:end] if start >= 0 and end > 0 else raus
        bewertungen = json.loads(raus)
        if not isinstance(bewertungen, list):
            raise ValueError("Kein Array")
    except Exception as e:
        print(f"  ⚠️ JSON-Parse Fehler: {e} — Fallback")
        bewertungen = [
            {"title": h.get("title", ""), "score": 50, "topics": ["sonstiges"],
             "tickers": [], "reason": "Fehler bei KI-Bewertung"}
            for h in headlines
        ]

    # Mit Original-Headlines mergen (für link, date, originale Ticker)
    ergebnis = []
    for bw in bewertungen:
        orig = next(
            (h for h in headlines
             if h.get("title", "").strip().lower() == bw.get("title", "").strip().lower()),
            {}
        )
        # Ticker: KI + Original zusammenführen
        tickers = list(set(
            (bw.get("tickers") or []) + (orig.get("tickers") or [])
        ))
        ergebnis.append({
            "title": orig.get("title", bw.get("title", "")),
            "score": int(bw.get("score", 50)),
            "topics": bw.get("topics", ["sonstiges"]),
            "tickers": tickers,
            "reason": bw.get("reason", ""),
            "link": orig.get("link", ""),
            "date": orig.get("date", ""),
        })
    return ergebnis


def ki_bewerte_news(headlines, max_tokens=1500):
    """Bewertet Headlines via zentraler KI-Provider-Kette (ki_provider.call_ki)."""
    if not headlines:
        return []
    try:
        from ki_provider import call_ki
    except Exception as e:
        print(f"  ❌ ki_provider nicht verfügbar: {e}")
        return []

    prompt = build_news_prompt(headlines)
    print(f"  🤖 KI-News-Bewertung ({len(headlines)} Headlines)...")

    raus, provider = call_ki(
        [
            {"role": "system", "content": "Du antwortest NUR mit einem gültigen JSON-Array. Kein Text, keine Erklärungen, keine Denkprozesse. Nur das Array."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,  # niedriger für striktes JSON
        max_tokens=max_tokens,
    )
    if not raus:
        print(f"  ❌ Alle Provider gescheitert")
        return []

    print(f"  ✅ Provider: {provider}")
    return parse_ki_response(raus, headlines)


def speichere_news_bewertungen(bewertungen):
    """Speichert News-Bewertungen in ki_log.json (typ='news')."""
    if not bewertungen:
        return 0
    log = lade_ki_log()
    jetzt = datetime.now().isoformat()

    for bw in bewertungen:
        score = bw.get("score", 50)
        stars = "⭐⭐⭐" if score >= 70 else ("⭐⭐" if score >= 45 else ("⭐" if score >= 20 else ""))
        log.append({
            "zeit": jetzt,
            "typ": "news",
            "title": bw.get("title", ""),
            "score": score,
            "stars": stars,
            "topics": bw.get("topics", ["sonstiges"]),
            "tickers": bw.get("tickers", []),
            "reason": bw.get("reason", ""),
            "link": bw.get("link", ""),
            "date": bw.get("date", ""),
        })

    # Trim auf 500
    if len(log) > 500:
        log = log[-500:]

    with open(KI_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

    print(f"  ✅ {len(bewertungen)} News bewertet & in ki_log.json gespeichert")
    return len(bewertungen)


def news_analyse(max_headlines=20, force=False, min_interval_h=2):
    """Hauptfunktion: Cache aktualisieren → neue bewerten → speichern.

    Args:
        max_headlines: Max. Headlines pro Lauf (Kosten-Kontrolle)
        force: Interval ignorieren
        min_interval_h: Mindestabstand zwischen KI-Bewertungen
    """
    print("📡 KI-News-Analyse...")

    # 1. Cache aktualisieren (RSS holen)
    update_news_cache()

    # 2. Prüfen ob Interval vergangen
    ki_log = lade_ki_log()
    letzte = letzte_news_evaluierung(ki_log)
    if not force and letzte:
        abstand = datetime.now() - letzte.replace(tzinfo=None)
        if abstand < timedelta(hours=min_interval_h):
            print(f"  ⏭️ Skip: letzte News-KI-Bewertung vor {abstand.seconds//60} Min "
                  f"(min {min_interval_h*60} Min)")
            return 0

    # 3. Unbewertete Headlines laden
    alle_news = lade_news()
    bekannte = bereits_bewertet_titel(ki_log)
    neue = [h for h in alle_news if h.get("title", "").strip().lower() not in bekannte]

    if not neue:
        print("  ℹ️ Keine neuen/unbewerteten Headlines.")
        return 0

    # Begrenzen
    neue = neue[:max_headlines]
    print(f"  🔍 {len(neue)} neue Headlines zur Bewertung...")

    # 4. KI bewerten (zentrale Fallback-Kette)
    bewertungen = ki_bewerte_news(neue)

    # 5. Speichern
    return speichere_news_bewertungen(bewertungen)


# ═══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    max_h = 20
    for arg in sys.argv:
        if arg.startswith("--max="):
            try:
                max_h = int(arg.split("=")[1])
            except:
                pass
    n = news_analyse(max_headlines=max_h, force=force)
    print(f"\nFertig: {n} News bewertet.")