> **⚠️ AKTUALITÄT:** Dieses Dokument ist **veraltet** (Stand vor R1–R5 + Settings-System).
> Die **zentrale, aktuelle Doku** ist `README.md` (gleicher Ordner).
> Dort: Architektur, alle Module, Settings-System, bekannte Fallen, Implementierungsstand.

# Micro-Trader KI-Lernsystem — Technische & Optische Dokumentation

**Zweck:** Vollständige, maschinenlesbare Beschreibung des autonomen Lernsystems für eine
unabhängige KI zur Verifikation (Code-Review, Fork, Audit).
**Stand:** 2026-08-02 | **Projekt-Pfad:** `C:/Users/goldi/projects/micro-trader`
**Laufzeit:** Python 3.12 (`C:/Program Files/Python312/python.exe`, NICHT Hermes-venv)
**Dashboard:** Port 5300 (Flask) | **Cron:** Hermes Job `c0e89575d724` (15min, KI-Mode)

---

## 1. System-Architektur (Überblick)

```
┌─────────────────────────────────────────────────────────────────┐
│  CRON (Hermes, 15min) → micro-trader-cron.py --mode ki          │
│       │ (PYTHONPATH/PYTHONHOME komplett entfernt vor Subprozess)  │
│       ▼                                                           │
│  micro-trader-pipeline.py --mode ki                              │
│       ├─ news_monitor.py     (RSS sammeln)                      │
│       ├─ ki_news.py          (KI-News-Bewertung + VORFILTER)    │
│       ├─ spec_trader.py      (Spekulations-Entscheidungen)      │
│       ├─ ki_decisions.py     (KI-Entscheidungen + Caps/Swaps)   │
│       ├─ ki_learning.py      (Lernmodul: Regeln, Scores)        │
│       └─ skill_sync.py       (Regeln → Hermes-Skill)            │
│                                                                  │
│  Engine-Cron (5min, kein LLM): boersen.py, engine.py, trader.py │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                   dashboard.py (Port 5300, Flask)
                   liest alle JSON-State-Files + ki_log.json
                   rendert Tabs (Aktien/ETF/Spek/Analyse/News/KI/Log)
                   KI-Tab hat 6 Subtabs (inkl. "Was die KI lernt")
```

### Kern-Dateien
| Datei | Verantwortlichkeit |
|-------|-------------------|
| `ki_learning.py` (1900+ Zeilen) | Lern-Engine: Regeln, Scores, Kalibrierung, Multiskalen |
| `learned_rules.py` | `learned_rules.json` als Source of Truth (CRUD + Status) |
| `ki_decisions.py` | KI-Entscheidungen pro Ticker + Anwendung von Caps/Swaps |
| `ki_news.py` | RSS + KI-News-Bewertung + irrelevante-Filter |
| `dashboard.py` | Flask-Backend, baut `/data`-JSON (gecached 30s) |
| `dashboard.html` | Frontend (Vanilla JS, Glassmorphism, Auto-Refresh 30s) |
| `engine.py` | Trader-Engine: Ausführung, Bremsen, Konzentrations-Limit |
| `ki_kontext.py` | Kontext-Block für KI-Prompts (RSI, Trend, Konzentration) |

---

## 2. Das Lern-Modell (7 Mechanismen)

Das System lernt **deterministisch + 1 KI-Call pro Zyklus**. Kein Reinforcement-Learning,
sondern regelbasierte Mustererkennung mit Gewichten.

### 2.1 Anti-Regeln (`[Anti]`-Präfix)
- **Quelle:** `anti_muster_regeln(ergebnisse)` in `ki_learning.py`
- **Logik:** Muster, die systematisch falsch lagen (z.B. "halten bei Volatility-Titeln" → 3/3 widerlegt)
- **Gewicht:** negativ (z.B. -1.88), fließt als **NICHT-Regel** in KI-Prompt
- **Prio 2:** `finde_konflikte()` erkennt widersprüchliche Regeln; `lebenszyklus_status()` archiviert veraltete

### 2.2 Swap-Regeln (`[Swap]`-Präfix, Typ `swap`)
- **Quelle:** `swap_score_berechnen(decisions)` in `ki_learning.py`
- **3 Typen:** `inner_portfolio` | `benchmark` (SPY) | `cash_reserve`
- **Logik:** Liefen "halten"-Positionen schlechter als Alternative? → Umschichtungs-Regel
- **Beispiel:** `[Swap] Kapital in Positionen blockiert Benchmark` (Gewicht 2.0)

### 2.3 Konfidenz-Caps (Meta-Regeln, Typ `meta_conf_cap`) — **PRIO 3**
- **Quelle:** `konfidenz_kalibrierung()` → `_konfidenz_caps_als_regeln()`
- **Logik:** Konfidenz-Binning (0-20, 20-40, ..., 80-100). Wenn Bin mit hoher Konfidenz
  aber niedriger Trefferquote (z.B. 80-100% → 0% Treffer) → Meta-Regel erzeugt
- **Anwendung:** `konfidenz_cap_aktuell()` liefert Min-Cap (aktuell **60**)
- **In `ki_decisions.entscheide_ticker()`:** KI-Konfidenz > Cap wird auf Cap gedrosselt
  (z.B. 95 → 60), Feld `konfidenz_original` bleibt erhalten
- **Persistenz:** `learned_rules.speichere_regeln()` behält `meta_conf_cap` (Filter erweitert)
- **Feld:** `conf_cap` in JSON (z.B. `{muster: "[Meta] Konfidenz-Cap 60...", conf_cap: 60}`)

### 2.4 Exit-Score — **PRIO 4**
- **Funktionen:** `exit_score_berechnen()`, `exit_score_entscheidung_ueberschreiben()`
- **Score (0-100):**
  - Trend intakt (Kurs > SMA20 > SMA50): +40
  - P&L unter Take-Profit (Luft nach oben): +30
  - RSI < 70 (nicht überkauft): +20
  - Momentum positiv (Kurs > SMA20): +10
- **Anwendung:** Wenn KI "verkaufen" will ABER Score ≥ 70 → wird zu **"halten"** überschrieben
  (Feld `exit_score`, `aktion_original: "verkaufen"`)
- **Ziel:** Verhindert Zu-früh-Verkäufe (Historie: Verkäufe liefen +4.4% weiter)

### 2.5 News-Swap — **PRIO 5**
- **Funktionen:** `news_swap_score()`, `news_swap_entscheidung_ueberschreiben()`
- **Logik:**
  - News-Impact < 75 → kein Swap
  - News-Impact ≥ 75 + P&L schwach (vs Benchmark -2%) → Score +50 (Basis 30)
  - P&L < 0 → +30; P&L < Benchmark-2 → +50
- **Anwendung:** Wenn KI "halten"/"kaufen" will ABER News-Swap-Score ≥ 60 → wird zu **"verkaufen"** (Umschichtung)
- **Feld:** `news_swap_score`

### 2.6 Multi-Timeframe-Regeln — **PRIO 6**
- **Funktion:** `multi_timeframe_regel_lernen(entscheidungen)`
- **ABHÄNGIGKEIT:** `lerneffekt_multiskalen(ticker, aktion)` (WURDE REPARIERT — fehlte komplett!)
  - Kombiniert 15m/4h/1d via `lerneffekt()`-Stufen: `0.3*s15m + 0.5*s4h + 0.2*s1d`
  - ATR-Normalisierung bei Volatilität > 5%
- **Logik:** Divergenz 15min vs 1d erkennen:
  - KI "kaufen" bei 15min↑/1d↓ → Anti-Regel "[MTF] Vorsicht Kaufen..." (G -1.0)
  - KI "verkaufen" bei 15min↓/1d↑ → Positiv-Regel "[MTF] Halten..." (G +1.0)

### 2.7 Konzentrations-Lernen — **PRIO 7**
- **Funktion:** `konzentrations_lernen(min_anz=4)`
- **Logik:** `ticker_konzentration(ticker)` zählt Depots mit offener Position
  - Ticker in ≥4 Depots → Anti-Regel "[Konzentration] X in N Depots" (G -0.2*N)
  - Beispiel: DOMO in 8 Depots → G -1.6
- **Ziel:** Klumpenrisiko vermeiden (Engine-Bremse blockiert ohnehin Kauf bei ≥4 Depots)

---

## 3. Datenfluss & Persistence

### learned_rules.json (Source of Truth)
```json
{
  "muster": "[Anti] halten bei volatility-Titeln",
  "regel": "NICHT halten bei volatility-Titeln – systematisch falsch (3/3 widerlegt)",
  "typ": "anti",                    // anti | swap | positiv | meta_conf_cap
  "gewicht": -1.88,
  "support_count": 3,
  "violation_count": 0,
  "avg_effect_when_applied": -4.3,
  "kontext": {"asset_klasse": [], "sektor": [], "vix_range": [0, 999], ...},
  "created_at": "2026-07-30T...",
  "updated_at": "2026-08-01T...",
  "last_seen_at": "2026-08-02T...",
  "decay_lambda": 0.01,            // exp(-0.01*t) Zeit-Decay
  "conf_cap": 60,                  // NUR bei meta_conf_cap
  "status": "stabil"               // stabil | wackelig | veraltet (Prio 2, berechnet)
}
```

### ki_log.json (Entscheidungs- & Lern-Historie)
- `typ: "decision"` — KI-Entscheidung (ticker, aktion, konfidenz, grund, exit_score, news_swap_score, ...)
- `typ: "learned"` — Lern-Notiz (notiz, kategorie: success/fehler/info/ki_bewertung, ...)
- `typ: "news"` — KI-News-Bewertung (score 0-100, stars, topics, tickers)

---

## 4. News-Filterung (irrelevante News raus) — **TASK 2**

### 4.1 VORFILTER (vor KI-Call, spart API-Kosten)
- **Datei:** `ki_news.py`, Funktion `ist_irrelevant(title)` + `update_news_cache()`
- **Logik:**
  1. **Blacklist** (Wort-exakt, nicht Substring — verhindert False-Positive wie "inflation"→"nfl"):
     celebrity, royal, kardashian, election 2024/2025/2026, sport, olymp, fifa, nba, nfl,
     entertainment, movie, fashion, lifestyle, recipe, travel, weather, horoskop, health,
     diet, dating, restaurant, game review, xbox, playstation, obituary, wedding, concert, tour, ...
  2. **Context-Blacklist:** wikipedia, how to, tutorial, opinion, sponsored, pressemitteilung, ...
  3. **Min-Länge:** < 4 Wörter → irrelevant
- **Metrik:** `update_news_cache()` zählt `irrelevant` (separat von `relevant`)
- **Verifikation:** 10 Test-Headlines, alle korrekt (kein False-Positive bei "Fed rate cut")

### 4.2 NACHFILTER (nach KI-Bewertung, im Dashboard)
- **Datei:** `dashboard.py`, `news_by_ticker`-Build (Zeile ~593)
- **Logik:** News mit `score < 20` (⭐ weniger als 1 Stern) werden NICHT in `news_by_ticker` aufgenommen
  → erscheinen nicht in Ticker-Detailansicht (News-Impact-Box) und nicht im News-Tab
- **Konstante:** `NEWS_MIN_SCORE = 20`
- **Verifikation:** 26 News im `news_by_ticker`, alle ≥ 20 (NFLX/WBD mit Score 5 werden ausgeblendet)

---

## 5. Dashboard (Optik & Technik)

### 5.1 Design-Sprache
- **Glassmorphismus / Apple-Stil**, heller Hintergrund (`--bg: #f4f5f9`)
- **Inter-Schrift** (Google Fonts), abgerundete Cards (radius 12px), weiche Schatten
- **Tabs:** Aktien | ETF | Spekulation | Analyse | News | KI-Log | Log
- **Auto-Refresh:** `setInterval(load, 30000)` — alle 30s neuer Fetch, Cache-Busting

### 5.2 KI-Tab (6 Subtabs)
1. 📊 **Auswertung** — Trefferquote, Ø Lerneffekt, Regel-Anzahl (KPI-Cards)
2. 🤖 **Entscheidungen** — KI-Log der Entscheidungen (aktion, konfidenz, grund)
3. 📰 **News-Bewertung** — KI-bewertete News mit Score/Sternen
4. 🧠 **Lerneffekte** — Lerneffekt-Verlauf pro Ticker
5. 📌 **Regeln & Skill** — Alle Regeln (Badges: stabil/wackelig/veraltet, Anti/Meta), Skill-Sync-Info
6. 📚 **Was die KI lernt** — **NEU (TASK 1)**

### 5.3 Subtab "📚 Was die KI lernt" (TASK 1)
- **Erklärt** die 7 Lern-Mechanismen (Beschreibung pro Mechanismus)
- **Live-Daten** aus `/data`:
  - `ki_lern_notizen` (letzte 15 Lern-Schritte aus `ki_log.json`, typ=learned) — auto-update
  - `ki_regeln` Status-Counter (stabil/positiv/anti/swap/meta-cap/konflikte) — live
  - `pending_rules` (wackelig/veraltet) — live
  - `konfidenz_cap` — aktiver Cap (z.B. 60)
- **Kreislauf-Diagramm** (Text): Trader → Engine misst → KI bewertet → Regeln → Prompts/Skill
- **Auto-Update:** Da im `load()`-Block (30s Refresh), aktualisiert sich automatisch

### 5.4 Backend `/data`-JSON (relevant für KI-Tab)
```json
{
  "ki_lern_notizen": [{"zeit": "...", "notiz": "...", "kategorie": "ki_bewertung"}, ...],
  "pending_rules": [{"muster": "...", "status": "wackelig"}, ...],
  "konfidenz_cap": 60,
  "ki_regeln": [{"muster": "...", "typ": "meta_conf_cap", "conf_cap": 60, "status": "stabil"}, ...],
  "regel_konflikte": 0,
  "news_by_ticker": {"AAPL": [90, "⭐⭐⭐", ["earnings", "tech"]], ...}  // alle >= 20
}
```

---

## 6. Bekannte Bugs (behoben in diesem Session)

| Bug | Ursache | Fix |
|-----|---------|-----|
| `lerneffekt_multiskalen` fehlte | Verwaister Code-Block ohne `def`-Kopf | Funktion rekonstruiert (Prio 6 hing davon ab) |
| `konfidenz_cap_aktuell` überschrieben | Patch-Kollision | Neu definiert vor `exit_score_*` |
| Meta-Regeln verworfen | `speichere_regeln()` Filter kannte `meta_conf_cap` nicht | Zu "immer behalten" hinzugefügt |
| `conf_cap`-Feld nicht persistiert | `speichere_regeln()` nahm nur bekannte Felder | `conf_cap` in Update/Neue-Regel-Logik ergänzt |
| Venv-Kontamination im Cron | Hermes-Scheduler erbt PYTHONPATH→venv (kaputt) | `micro-trader-cron.py` entfernt PYTHONPATH+PYTHONHOME komplett |
| 7 Zombie-Dashboard-Prozesse auf 5300 | Viele Neustarts ohne Cleanup | Via PowerShell PIDs identifiziert + gekillt, nur 1 frischer Prozess |

---

## 7. Verifikation (Status 2026-08-02 13:50)

| Test | Ergebnis |
|------|----------|
| `konfidenz_cap_aktuell()` | 60 ✓ |
| `exit_score_berechnen()` (Trend intakt) | 100 → "halten" ✓ |
| `news_swap_score()` (News 90 + schwach) | 80 → "verkaufen" ✓ |
| `multi_timeframe_regel_lernen()` | 2 Regeln (ABC anti, XYZ positiv) ✓ |
| `konzentrations_lernen()` (DOMO 8 Depots) | 1 Anti-Regel G -1.6 ✓ |
| `ist_irrelevant()` (10 Tests) | alle korrekt, kein False-Positive ✓ |
| Dashboard `/data` (5300) | ki_lern_notizen: 291, cap: 60, news alle ≥20 ✓ |
| Cron-Lauf (--mode ki) | Pipeline OK, ki_learning 51s, keine Fehler ✓ |

---

## 8. Für eine andere KI (Audit-Checkliste)

1. **Python:** Nutze `C:/Program Files/Python312/python.exe` mit `env -u PYTHONPATH` (venv kaputt)
2. **Kein LLM nötig** für Tests — alle Funktionen sind deterministisch (Mock möglich)
3. **learned_rules.json** ist Source of Truth — nie direkt editieren, immer über `speichere_regeln()`
4. **Cron:** `micro-trader-cron.py` MUSS `PYTHONPATH=""` + `PYTHONHOME` entfernen (sonst openai-Fehler)
5. **Dashboard:** Nur EIN Prozess auf 5300 (Zombies via `Get-NetTCPConnection -LocalPort 5300` finden)
6. **Tests:** `ki_learning.py` direkt importierbar; `dashboard.data()` cached 30s (Cache vor Test löschen)
7. **Neue Regel-Typen:** Bei `speichere_regeln()` immer zu `immer_behalten` hinzufügen (sonst verloren)

---

*Generiert zur Verifikation durch eine unabhängige KI. Alle Pfade, Funktionen und Verifikations-
ergebnisse sind aus dem live laufenden System extrahiert (nicht hypothetisch).*
