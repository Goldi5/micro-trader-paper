#!/usr/bin/env python3
"""Bewertet News-Headlines via KI (ki_provider-Pool, P2-Fix 2026-08-11)
und speichert strukturiert in ki_log.json.

FIX (2026-08-11, Roadmap Punkt 2):
- Alten OPENCODE_GO_API_KEY/Zen-Direktaufruf ersetzt durch ki_provider.call_ki
  (openrouter Primary, nous-hy3/step, zen ling — reparierter Pool)
- Ticker-Mapping aus Watchlist/Depots (statt nur KI-Raten)
- Deduplizierung via Hash(title+url)
- Prioritaet P0-P3 (Roadmap Punkt 3)

Aufruf: python news_evaluator.py
"""
import json, os, sys, time, hashlib
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
NEWS_CACHE = os.path.join(BASE, "news_cache.json")
KI_LOG    = os.path.join(BASE, "ki_log.json")

MINDEST_ABSTAND = timedelta(hours=2)
BATCH_SIZE = 10

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

def bekannt_titel(ki_log):
    return {e.get("title", "").strip().lower() for e in ki_log}

def letzte_evaluierung(ki_log):
    zeiten = []
    for e in ki_log:
        z = e.get("zeit", "")
        if z:
            try:
                zeiten.append(datetime.fromisoformat(z))
            except ValueError:
                pass
    return max(zeiten) if zeiten else None

def ticker_map():
    """Ticker aus Watchlist + Spec-Depots + Aktien/ETF-Paper (fuer News-Zuordnung)."""
    t = {}
    try:
        from spec_watch import WATCHLIST
        for tk, meta in WATCHLIST.items():
            t[tk.upper()] = meta.get("name", tk)
    except Exception:
        pass
    for f in __import__("glob").glob(os.path.join(BASE, "spec_depots", "*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("ticker"):
                t[d["ticker"].upper()] = d.get("name", d["ticker"])
        except Exception:
            pass
    for pat in ["depot_*_paper.json", "etf_*_paper.json"]:
        for f in __import__("glob").glob(os.path.join(BASE, pat)):
            try:
                d = json.load(open(f, encoding="utf-8"))
                for tk in (d.get("positions", {}) or {}).keys():
                    t[tk.upper()] = tk
            except Exception:
                pass
    return t


# Fix 2: Firmenname -> Ticker (fuer News-Fallback, wenn KI nur Namen liefert)
_STATISCHE_FIRMEN = {
    "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "facebook": "META", "tesla": "TSLA",
    "nvidia": "NVDA", "netflix": "NFLX", "intel": "INTC", "amd": "AMD",
    "palantir": "PLTR", "nio": "NIO", "coinbase": "COIN", "micron": "MU",
    "berkshire": "BRK.B", "jpmorgan": "JPM", "goldman sachs": "GS",
    "boeing": "BA", "exxon": "XOM", "pfizer": "PFE", "moderna": "MRNA",
    "gamestop": "GME", "amc": "AMC", "robinhood": "HOOD", "uber": "UBER",
    "airbnb": "ABNB", "salesforce": "CRM", "adobe": "ADBE", "paypal": "PYPL",
    "biogen": "BIIB", "crispr": "CRSP", "crispr therapeutics": "CRSP",
    "bbai": "BBAI", "bigbear": "BBAI", "fngu": "FNGU", "fngo": "FNGO",
}
def firmenname_map():
    """Name -> Ticker (aus Depot-Namen + statischer Liste)."""
    m = {}
    # aus ticker_map(): Name -> Ticker
    for tk, name in ticker_map().items():
        if name and name != tk:
            m[name] = tk
    m.update(_STATISCHE_FIRMEN)
    return m

def dedup_hash(title, link=""):
    return hashlib.md5(f"{title.strip().lower()}|{link}".encode()).hexdigest()[:12]

def batch_evaluieren(headlines, ticker_known):
    """Sendet Batch an ki_provider.call_ki (reparierter Pool) und parst JSON."""
    ticker_str = ", ".join(sorted(ticker_known)[:25]) or "keine"
    prompt = (
        "Du bewertest Börsen-News für ein Paper-Trading-System. "
        "Bekannte Ticker: " + ticker_str + ".\n\n"
        "Gib ein JSON-Array zurück:\n\n"
        "[{\"title\": \"Headline\", \"score\": 0-100, \"topics\": [\"markt\",\"tech\",\"earnings\",\n"
        " \"geopolitik\",\"energie\",\"zinsen\",\"regulation\",\"sonstiges\"],\n"
        " \"tickers\": [\"AAPL\"], \"urgency\": \"P0|P1|P2|P3\", \"event_type\": \"earnings|ma|guidance|regulierung|sonstiges\",\n"
        " \"direction\": \"positive|negative|neutral\", \"reason\": \"kurzer Grund\"}]\n\n"
        "Score = Relevanz fuer Aktien-Trading (0=unwichtig, 100=sehr relevant).\n"
        "P0=Insolvenz/Handelsaussetzung/UEbernahmeangebot, P1=Earnings/Guidance, P2=normal, P3=Archiv.\n"
        "Nenne Ticker nur wenn erkennbar. Antworte NUR mit dem JSON-Array.\n\n"
        "Headlines:\n"
    )
    for h in headlines:
        prompt += f"- {h.get('title','?')}\n"

    try:
        import ki_provider
        raus, _prov = ki_provider.call_ki(
            [{"role": "system", "content": "Du antwortest NUR mit JSON."},
             {"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=4096,
        )
        if not raus:
            raise ValueError("leere KI-Antwort")
        start = raus.find("[")
        end  = raus.rfind("]") + 1
        raus = raus[start:end] if start >= 0 and end > 0 else raus
        bewertungen = json.loads(raus)
        if not isinstance(bewertungen, list):
            raise ValueError("Kein Array")
        return bewertungen
    except Exception as e:
        print(f"Fehler bei KI-Evaluierung: {e}", file=sys.stderr)
        return [{"title": h.get("title",""), "score": 50, "topics": ["sonstiges"],
                 "tickers": [], "urgency": "P2", "event_type": "sonstiges",
                 "direction": "neutral", "reason": "Fehler bei KI-Bewertung"}
                for h in headlines]

def sternzahl(score):
    if score >= 70:  return "⭐⭐⭐"
    elif score >= 45: return "⭐⭐"
    elif score >= 20: return "⭐"
    return ""

def main():
    jetzt = datetime.now().isoformat()
    news = lade_news()
    ki_log = lade_ki_log()
    if not news:
        print("Keine News vorhanden.")
        return

    letzte = letzte_evaluierung(ki_log)
    if letzte:
        abstand = datetime.now() - letzte.replace(tzinfo=None)
        if abstand < MINDEST_ABSTAND:
            print(f"Skip: letzte Evaluierung vor {int(abstand.total_seconds()//60)} Min "
                  f"(min {int(MINDEST_ABSTAND.total_seconds()//60)} Min)")
            return

    bekannte = bekannt_titel(ki_log)
    neue = [h for h in news if h.get("title","").strip().lower() not in bekannte]
    if not neue:
        print("Keine neuen/unbewerteten Headlines.")
        return

    tknown = ticker_map()
    print(f"Bewerte {len(neue)} neue Headlines (von {len(news)} gesamt, "
          f"{len(tknown)} bekannte Ticker)...")

    neue_eintraege = []
    for i in range(0, len(neue), BATCH_SIZE):
        batch = neue[i:i+BATCH_SIZE]
        bewertungen = batch_evaluieren(batch, tknown)
        for bw in bewertungen:
            orig = next((h for h in batch if h.get("title","").strip().lower() == bw.get("title","").strip().lower()),
                        batch[0] if batch else {})
            titel = orig.get("title", bw.get("title", ""))
            score = bw.get("score", 50)
            tickers = [t.upper() for t in (bw.get("tickers") or []) if t.upper() in tknown]
            # Fix 2: Firmenname-Fallback (wenn KI nur Namen nennt, nicht Ticker)
            if not tickers:
                fn_map = firmenname_map()
                titel_l = titel.lower()
                for name, tk in fn_map.items():
                    if name.lower() in titel_l and tk in tknown:
                        tickers = [tk]
                        break
            neue_eintraege.append({
                "zeit": jetzt,
                "typ": "news",
                "title": titel,
                "score": score,
                "stars": sternzahl(score),
                "topics": bw.get("topics", ["sonstiges"]),
                "tickers": tickers,
                "urgency": bw.get("urgency", "P2"),
                "event_type": bw.get("event_type", "sonstiges"),
                "direction": bw.get("direction", "neutral"),
                "reason": bw.get("reason", ""),
                "link": orig.get("link", ""),
                "dedup_id": dedup_hash(titel, orig.get("link", "")),
            })
        if i + BATCH_SIZE < len(neue):
            time.sleep(1)

    # Dedup: gleiche dedup_id nur einmal
    gesehen = set()
    gefiltert = []
    for e in neue_eintraege:
        if e["dedup_id"] not in gesehen:
            gesehen.add(e["dedup_id"])
            gefiltert.append(e)

    ki_log.extend(gefiltert)
    if len(ki_log) > 500:
        ki_log = ki_log[-500:]

    with open(KI_LOG, "w", encoding="utf-8") as f:
        json.dump(ki_log, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(gefiltert)} Headlines bewertet (nach Dedup) – ki_log.json aktualisiert "
          f"(jetzt {len(ki_log)} Einträge gesamt)")

if __name__ == "__main__":
    main()
