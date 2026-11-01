#!/usr/bin/env python3
"""
News-Monitor – holt stündlich Wirtschafts- und Aktien-Headlines.
"""
import json, os, time, socket
from datetime import datetime
import urllib.request, urllib.error
import xml.etree.ElementTree as ET

BASE = os.path.dirname(os.path.abspath(__file__))
NEWS_CACHE = os.path.join(BASE, "news_cache.json")

# RSS-Feeds (kein API-Key nötig)
FEEDS = [
    "https://feeds.content.dowjones.io/public/rss/mw_topstories",
    "https://finance.yahoo.com/news/rssindex",
    "https://www.investopedia.com/feedbuilder/feed/getfeed?feedName=rss_headlines",
    "https://feeds.bloomberg.com/markets/news.rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/Economy.xml",
]

KEYWORDS = {
    "interest rate": ["interest rate", "fed", "federal reserve", "rate hike", "rate cut", "zins"],
    "earnings": ["earnings", "quarterly results", "gewinn", "results"],
    "merger": ["merger", "acquisition", "übernahme", "buyout", "takeover"],
    "regulation": ["regulation", "sec", "regulatory", "regulierung", "klage", "lawsuit"],
    "recession": ["recession", "recession fears", "wirtschaftskrise", "recession warning"],
    "inflation": ["inflation", "cpi", "consumer price", "inflation data"],
    "tech": ["tech", "technology", "semiconductor", "ai", "chip", "künstliche intelligenz"],
    "energy": ["oil", "crude", "energy", "gas", "öl", "energie"],
    "market": ["market", "stock market", "dow", "s&p", "nasdaq", "index"],
    "geopolitics": ["war", "conflict", "trade war", "tariff", "zoll", "sanktion", "sanction"],
    "crypto": ["bitcoin", "crypto", "blockchain", "ethereum", "krypto"],
}

def fetch_rss(url, timeout=10):
    """Holt einen RSS-Feed und gibt (items, fehler) zurück.
    fehler: None | 'timeout' | 'http' | 'parse' | 'other' (für Fehlerklassen-Tracking)."""
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
        return items, None
    except urllib.error.HTTPError as e:
        # 429 = Rate-Limit, 403 = forbidden, 404 = not found
        kind = "ratelimit" if e.code == 429 else "http"
        return [], kind
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        return [], "timeout"
    except ET.ParseError:
        return [], "parse"
    except Exception as e:
        return [], "other"

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

def update_news():
    """Holt aktuelle News und speichert sie."""
    alle = []
    feed_status = {}  # url -> (count, fehler) für Monitoring
    for url in FEEDS:
        items, fehler = fetch_rss(url)
        host = url.split('/')[2]
        if fehler:
            feed_status[host] = (0, fehler)
            print(f"  ⚠️ {host}: FEHLER ({fehler})")
        else:
            feed_status[host] = (len(items), None)
            if items:
                print(f"  ✅ {len(items)} von {host}")
        alle.extend(items[:15])  # max 15 pro Feed
        time.sleep(1)

    # Relevante Headlines
    relevant = []
    seen_titles = set()  # Phase 4: Deduplizierung
    for item in alle:
        title_norm = item["title"].strip().lower()
        if title_norm in seen_titles:
            continue  # Duplikat ueberspringen
        seen_titles.add(title_norm)
        cats = classify_headline(item["title"])
        if cats:
            relevant.append({**item, "topics": cats})

    # Nach Tickern suchen (Phase 4: zentrale Mapping-Tabelle)
    from news_ticker_map import find_tickers
    for item in relevant:
        tickers_found = find_tickers(item["title"])
        if tickers_found:
            item["tickers"] = tickers_found

    data = {
        "zeit": datetime.now().isoformat(),
        "total": len(alle),
        "relevant": len(relevant),
        "feed_status": feed_status,
        "headlines": relevant[:30] if relevant else [{"title": "Keine relevanten News"}],
    }
    with open(NEWS_CACHE, "w") as f:
        json.dump(data, f, indent=2)

    print(f"\n  📰 {len(alle)} Headlines gesammet, {len(relevant)} relevant")
    for h in relevant[:5]:
        print(f"    • {h['title'][:100]}")

if __name__ == "__main__":
    print("  📡 News-Monitor...")
    update_news()
