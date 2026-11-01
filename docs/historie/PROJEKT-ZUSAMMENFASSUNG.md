# Micro-Trader — Projekt-Zusammenfassung (Technik + Optik, Tab für Tab)

**Stand:** 2026-08-02 | **Pfad:** `C:/Users/goldi/projects/micro-trader`
**Laufzeit:** Python 3.12 (`C:/Program Files/Python312/python.exe`)
**Dashboard:** Flask auf Port 5300 | **Auto-Refresh:** 30 Sekunden (`setInterval(load, 30000)`)
**Cron:** Hermes Job `c0e89575d724` (alle 15 Min, `--mode ki`)

---

## 0. Architektur im Überblick

```
CRON (15min, KI-Mode)
  └─ micro-trader-pipeline.py
       ├─ news_monitor.py     → RSS sammeln
       ├─ ki_news.py          → KI-News-Bewertung (Score 0–100) + Vorfilter irrelevante
       ├─ spec_trader.py      → Spekulations-Entscheidungen (48 Ticker-Watchlist)
       ├─ ki_decisions.py     → KI-Entscheidungen + Caps/Swaps/Exit-Score
       ├─ ki_learning.py      → Lernmodul (Regeln, Scores, Kalibrierung)
       └─ skill_sync.py       → Regeln → Hermes-Skill (ki-trading-learning-loop)

ENGINE-CRON (5min, kein LLM)
  └─ boersen.py + engine.py + trader.py → Ausführung, Bremsen, Stop-Loss/Take-Profit

DASHBOARD (5300)
  └─ dashboard.py (Flask) → /data JSON (30s Cache) → dashboard.html (Vanilla JS, Glassmorphism)
```

**Design-Sprache:** Helles Glassmorphismus / Apple-Stil. Inter-Schrift (Google Fonts),
abgerundete Cards (radius 12px), weiche Schatten, Pastell-Akzente. Tabs oben, Subtabs bei KI.

---

## 1. Tab: 📊 Übersicht (panel-overview)

**Optik:** Hero-Header mit Gesamtwert + Gesamt-Rendite (große Zahl, grün/rot),
darunter 3 KPI-Cards (Aktien-Wert, ETF-Wert, Spec-Wert), dann ein Grid aus Depot-Cards
pro Risikostufe (Risk 0–95 in 5er-Schritten). Jede Card: Ticker/Label, Sektor-Badges,
Wert, Rendite %, Meta (Positionen · Cash · Trades · MaxDD · 🔒 gesperrt), KI-Icon.

**Technik:** `renderOverview()` baut HTML aus `d.depots + d.etf_depots + d.spec_depots`.
Klick auf Card → `showDepot(dep, typ)` öffnet Detail-Panel (panel-detail) mit
- Positionen-Tabelle (Shares, Ø-Kauf, Wert, P&L)
- Canvas-Chart (Kursverlauf, 140px)
- **News-Impact-Box** (falls Ticker News hat: `news_by_ticker[ticker]` → Score/Sterne)
- **KI-Entscheidung** (letzte Aktion, Konfidenz, Begründung)

**Was die KI hier sichtbar macht:** Pro Depot `ki_letzte` (zuletzt entschieden: kaufen/verkaufen/halten + Konfidenz).

---

## 2. Tab: 📈 Aktien (panel-stocks)

**Optik:** Summary-Row (Gesamtwert, Rendite, Depot-Anzahl, Aktiv, Trades), dann Grid mit
`renderCard()` pro Aktien-Depot (Risk-Stufe als "Risk X").

**Was die KI bewertet/tradet:**
- Aktien-Depots sind **20 Risikostufen** (Risk 0, 5, 10 … 95). Jede Stufe = eigenes Pseudo-Depot.
- `trader.py` Parameter pro Stufe:
  - **Risk 0–20 (konservativ):** position_size 35%, Stop-Loss −8%, Take-Profit +12%
  - **Risk 50+ (aggressiv):** position_size 50%, Stop-Loss −15%, Take-Profit +20%
- `ki_decisions.entscheide_aktien_depot()` fragt LLM (deepseek-v4-flash-free) mit:
  - Marktkontext (RSI, SMA20/50, Trend, Sektor)
  - Gelernte Regeln (Anti/Swap/Meta-Cap) als Prompt-Constraints
  - **Konfidenz-Cap** (aktuell 60): KI-Konfidenz > 60 wird auf 60 gedrosselt
  - **Exit-Score:** Bei Verkauf-Wunsch + intaktem Trend → "halten" (Score ≥70)
  - **News-Swap:** Bei News-Impact ≥75 + schwacher Position → "verkaufen"
- `engine.ausführen()` führt aus: Stop-Loss/Take-Profit-Trigger, **Konzentrations-Bremse**
  (Kauf blockiert wenn Ticker schon in ≥4 Depots), **Drawdown-Sperre** (Depot >30% unter
  Allzeithoch → `gesperrt=True`, keine neuen Trades).

**Gelernt wird:** Pro entschiedenem Ticker → `ki_log.json` (typ=decision). Engine misst
Kurs nach 4h/1d/1w → Lerneffekt −5…+5 → `ki_learning.analysiere_entscheidungen()`
erzeugt Anti-Regeln (z.B. "halten bei Volatility-Titeln"), Swap-Regeln, Multi-Timeframe-Regeln.

---

## 3. Tab: 📦 ETF (panel-etf)

**Optik:** Summary-Row (ETF-Gesamtwert, Rendite, ETF-Depot-Anzahl). Pro ETF-Depot eine
Glass-Card: "Risk X" + Risikostufen-Label (Geldmarkt/Anleihen/Breiter Markt/Sektor-Rohstoff/
Thema-Innovation/Gehebelt), Wert, Rendite, Positionen/Trades, **MaxDD** (rot wenn >10%),
Positionen-Liste (Ticker, Name, Shares, Ø-Kauf), 🔒-Hinweis wenn gesperrt, Fortschrittsbalken.

**Risikostufen (6 Stufen):** `etfStufen = [Geldmarkt, Anleihen, Breiter Markt, Sektor/Rohstoff, Thema/Innovation, Gehebelt]` (Risk/20 → Index 0–5).

**Was die KI bewertet/tradet:**
- `etf_trader.py` nutzt `ki_decisions` für ETF-Depots (gleiche Logik wie Aktien, aber
  längerer Horizont, weniger Hebel).
- ETFs sind die **Benchmark** für Swap-Regeln (SPY als Referenz: "liefen halte-Positionen
  schlechter als SPY?").
- **Konzentrations-Lernen:** DOMO z.B. in 8 Depots → Anti-Regel "lieber streuen".

**Gelernt wird:** ETF-Performance fließt in `swap_score_berechnen()` (benchmark_swap):
Wenn Halte-Position schlechter als SPY → Umschichtungs-Regel.

---

## 4. Tab: 🔥 Spekulation (panel-spec)

**Optik:** 3 Subtabs:
1. **Übersicht:** Spec-Gesamtwert, Ø-Rendite, Aktive Pos., Beobachtet. Dann 2-Spalten
   "Top-Gewinner (24h)" / "Top-Verlierer (24h)" mit CSS-Bars (grün/rot, proportional).
   Bester/Schlechtester Ticker hervorgehoben.
2. **Positionen (N):** Grid mit `renderCard()` pro Spec-Depot (spekulative Ticker mit Hebel).
3. **Watchlist (N):** Sortierbare Tabelle (Ticker, Name, Preis, 24h, 5T, Vola, Hebel, Kat.)
   mit Kategorie-Filter-Buttons. Klick auf Zeile → Mini-Chart (Canvas, 70px) inline.

**Kategorie-Farben:** index=cyan, crypto=amber, lev-bull=green, lev-bear=red, inverse=purple,
volatility=orange, commodity=lime, meme=pink, ai=blue, ev=cyan, biotech=indigo, space=orange.

**Was die KI bewertet/tradet (die 48 Ticker der WATCHLIST):**
- **Crypto:** IBIT, ETHA, BITO, BITX, ETHU (1–2x), MSTR, COIN, MARA, RIOT (Krypto-exposed)
- **Inverse (3x Bear):** SQQQ, SPXS, SPXU, SOXS, FAZ, JDST
- **Volatility:** UVXY (1.5x), VIXY, VXX, SVXY (−1x), BOIL, UCO, KOLD, SCO
- **Lev. Bull (3x):** TQQQ, FAS, FNGU, LABU, UPRO, TNA
- **Lev. Bear:** SPXU, SOXS, FAZ, JDST
- **Meme:** GME, AMC, BB
- **AI:** IONQ, RGTI, SOUN, BBAI, PLTR
- **EV:** RIVN, QS, JOBY
- **Biotech:** CRSP, MRNA, MNMD
- **Space:** RKLB, ASTS
- **Index (Benchmark):** SPY, QQQ

`spec_trader.py` → `entscheide_spec_batch()` (parallel, 8 Worker) fragt LLM pro Ticker mit:
- Tagesrendite, 5-Tage-Trend, Volatilität, Hebel, Kategorie
- News-Impact (falls vorhanden)
- **Konfidenz-Cap** + **Exit-Score** + **News-Swap** (wie Aktien)
- `fetch_analyse()` lädt 6-Monats-Kursdaten für Momentum/Volatilitäts-Metriken

**Gelernt wird:** Spekulations-Entscheidungen → `ki_log.json`. Anti-Regeln für
Kategorien, die systematisch falsch lagen (z.B. "halten bei lev-bull-Titeln" → 5/5 widerlegt).

---

## 5. Tab: 📊 Analyse (panel-analyse)

**Optik:** Summary-Row (Gesamtwert, Gesamt-Rendite, Trades Total). Dann pro Kategorie
(Aktien/ETF/Spekulation) eine `cssBar()`-Sektion:
- Horizontale CSS-Balken für **Top-Ticker** (Rendite-basiert, grün/rot)
- **Grund-Statistik:** Wie oft welche Begründung ("RSI überkauft", "Breakout", "News") →
  Trefferquote der Begründung (lernt: welche Gründe funktionieren)

**Technik:** `fetch("/api/analysis")` → `batch_summary.json` + `analyse_summary`.
Fällt API aus → "Analyse-Daten noch nicht verfügbar".

**Was die KI lernt (sichtbar):** `grund_stats` zeigt, welche Begründungs-Muster bestätigt
wurden (aus `ki_learning._grund_text_analyse()`). Das ist die **Grund-Text-Analyse**:
Clustert KI-Begründungen, misst Trefferquote pro Cluster → fließt in `learned_rules.json`.

---

## 6. Tab: 📰 News (panel-news)

**Optik:** Glass-Card-Liste, jede News: Titel (Link), Quelle · Datum.

**Was die KI bewertet:**
- `news_monitor.py` holt RSS von 5 Feeds (MarketWatch, Yahoo, Investopedia, Bloomberg, NYT Economy)
- `ki_news.py`:
  1. **VORFILTER** (`ist_irrelevant`): Blacklist (celebrity, sport, nba, royal, lifestyle,
     diet, dating, xbox, etc.) + Context-Filter (wiki, how-to, sponsored) + Min-Länge 4 Wörter.
     **Wort-exakt** (kein Substring → kein False-Positive wie "inflation"→"nfl").
  2. `classify_headline()`: 12 Themen (zinsen, earnings, m&a, regulation, rezession,
     inflation, tech, energy, markt, geopol, krypto)
  3. `find_tickers()`: Ticker-Erkennung (AAPL, TSLA, NVDA, …)
  4. **KI-Bewertung** (`ki_bewerte_news`): LLM vergibt Score 0–100 + Sterne + Topics
  5. **NACHFILTER** (dashboard.py): News mit Score < 20 werden aus `news_by_ticker` entfernt
     → erscheinen NIRGENDS (weder News-Tab noch Ticker-Detail)

**Persistenz:** `news_cache.json` (relevant/irrelevant Counter) + `ki_log.json` (typ=news).

---

## 7. Tab: 🤖 KI-Log (panel-ki) — 6 Subtabs

### 7.1 📊 Auswertung
KPI-Cards: Trefferquote (24h), Ø Lerneffekt (−5…+5 Skala), Gewichtete Regeln.
Dann Balken: Bestätigt/Leicht bestätigt/Neutral/Leicht widerlegt/Widerlegt (Farbcodiert).
Zeigt Visibilität des Lern-Erfolgs.

### 7.2 🤖 Entscheidungen
Liste aller KI-Entscheidungen (typ=decision): Ticker, Aktion (🟢kaufen/🔴verkaufen/⚪halten),
Konfidenz, Begründung. Zeigt `konfidenz_original` vs `konfidenz` (Cap angewendet),
`exit_score`, `news_swap_score`, `aktion_original`.

### 7.3 📰 News-Bewertung
KI-bewertete News: Titel, Score/Sterne, Topics.

### 7.4 🧠 Lerneffekte
Lerneffekt-Verlauf pro Ticker (aus `ki_log.json` typ=decision mit Lerneffekt-Wert).

### 7.5 📌 Regeln & Skill
Alle Regeln aus `learned_rules.json` (sortiert nach Gewicht):
- **Badges:** Meta (gelb), Anti (rot), Swap (lila), Positiv (grün)
- **Status:** stabil / wackelig / veraltet (Prio 2: `lebenszyklus_status()`)
- **Konflikt-Banner** falls widersprüchliche Regeln (`finde_konflikte()`)
- **Skill-Sync-Info:** Top-5 Regeln → Hermes-Skill `ki-trading-learning-loop`

### 7.6 📚 Was die KI lernt (NEU)
Erklärt die **7 Lern-Mechanismen** + zeigt **Live-Daten** (auto-update 30s):
- `ki_lern_notizen` (letzte 15 Lern-Schritte aus `ki_log.json` typ=learned)
- Regel-Status-Counter (stabil/positiv/anti/swap/meta-cap/konflikte)
- `pending_rules` (wackelig/veraltet)
- Aktiver `konfidenz_cap` (60)
- Kreislauf-Diagramm: Trader → Engine misst → KI bewertet → Regeln → Prompts/Skill

---

## 8. Tab: 📋 Log (panel-log)

**Optik:** System-Log (neueste zuerst), jeder Eintrag: Zeit, Quellen-Icon (cron/spec/batch/
etf/ki_learning/ki_decisions/system), Level-Icon (🟢ok/ℹ️info/🟡warn/🔴error), Text.

**Technik:** `system_log.json` (letzte 200 Einträge, reversed). Zeigt Cron-Läufe,
Pipeline-Schritte, Fehler.

---

## 9. Was die KI lernt — Zusammenfassung aller 7 Mechanismen

| # | Mechanismus | Quelle | Logik | Anwendung |
|---|-------------|--------|-------|-----------|
| 1 | **Anti-Regeln** | `anti_muster_regeln()` | Muster systematisch falsch → Verbot | Prompt-Constraint (NICHT-Regel) |
| 2 | **Swap-Regeln** | `swap_score_berechnen()` | Halte-Position schlechter als Benchmark? | Umschichtungs-Regel (3 Typen) |
| 3 | **Konfidenz-Cap** | `konfidenz_kalibrierung()` | Bin mit hoher Konf. aber 0% Treffer | KI-Konfidenz gedrosselt (60) |
| 4 | **Exit-Score** | `exit_score_berechnen()` | Trend intakt + Verkauf-Wunsch | Verkauf → "halten" (Score ≥70) |
| 5 | **News-Swap** | `news_swap_score()` | News ≥75 + schwach | Halten → "verkaufen" (Score ≥60) |
| 6 | **Multi-Timeframe** | `multi_timeframe_regel_lernen()` | 15min↑/1d↓ Divergenz | Anti/Positiv-Regel |
| 7 | **Konzentrations-Lernen** | `konzentrations_lernen()` | Ticker in ≥4 Depots | Anti-Regel "streuen" |

**Datenfluss:** Trading → `ki_log.json` (decision) → Engine misst Kurs → Lerneffekt
(−5…+5) → `ki_learning.analysiere_entscheidungen()` → Regeln → `learned_rules.json`
→ nächste KI-Prompts + Hermes-Skill (skill_sync.py).

---

## 10. Bekannte Bugs (behoben)

1. `lerneffekt_multiskalen()` fehlte komplett → rekonstruiert
2. `konfidenz_cap_aktuell()` durch Patch überschrieben → neu definiert
3. Meta-Regeln von `speichere_regeln()` verworfen → Filter erweitert
4. `conf_cap`-Feld nicht persistiert → ergänzt
5. Venv-Kontamination im Cron → PYTHONPATH/PYTHONHOME entfernt
6. 7 Zombie-Dashboard-Prozesse auf 5300 → via PowerShell PIDs gekillt

---

*Alle Angaben aus live laufendem System extrahiert (nicht hypothetisch).*
*Dashboard: Port 5300 HTTP 200, Cron: letzter Lauf OK, 291 Lern-Notizen, Cap 60, 26 relevante News.*
