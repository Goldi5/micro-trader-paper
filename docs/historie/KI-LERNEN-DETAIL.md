> **⚠️ AKTUALITÄT:** Dieses Dokument ist **veraltet** (Stand vor R1–R5 + Settings-System).
> Die **zentrale, aktuelle Doku** ist `README.md` (gleicher Ordner).

# Micro-Trader — KI-Lernen & Skill-Fütterung (DETAILLIERTE AUFSCHLÜSSELUNG)

**Stand:** 01.08.2026 · **System:** Windows 11, Python 3.12, yfinance, Flask-Dashboard :5300
**Zweck:** Vollständige, faktenbasierte Dokumentation für eine andere KI / einen Entwickler.
Alle Zahlen aus den echten Dateien (`ki_regeln.json`, `ki_log.json`, `ki_learning.py`, `pipeline.py`, `skill_sync.py`) zum Stand 01.08.2026 12:30.

---

## TEIL A — ARCHITEKTUR IM DETAIL

### A.1 Datenfluss (Schritt für Schritt)

```
[1] Cron (Hermes) alle 3 Min
        │
        ▼
[2] micro-trader-pipeline.py  (detached, CREATE_NO_WINDOW, PY=C:\Program Files\Python312\python.exe)
        │  setzt PYTHONPATH="" (Venv-Kontamination vermeiden), ruft nacheinander auf:
        │
        ├─ news_monitor.py        (sammelt Roh-News, keine KI)
        ├─ ki_news.py --max=5      (KI bewertet News je Ticker → ki_log typ=news)
        ├─ spec_trader.py          (nur wenn US offen: 48 Spec-Depots analysieren)
        ├─ etf_trader.py           (nur wenn Xetra offen: 20 ETF-Depots)
        ├─ batch_trader.py         (nur wenn US offen: 20 Aktien-Depots)
        ├─ ki_learning.py          (Lern-Analyse aller neuen Entscheidungen)
        └─ skill_sync.py           (Top-5 Regeln → Hermes-Skill)
        │
        ▼
[3] ki_decisions.py  (pro Depot/Ticker: baut Prompt + ruft ki_provider.call_ki)
        │
        ▼
[4] ki_provider.py  (Fallback-Kette: openai→zen→nous-step→nous-hy3→openrouter)
        │  LLM liefert JSON: {ticker, aktion, konfidenz, grund}
        ▼
[5] engine.ausführen()  (Trader führt aus NUR wenn alle Bremsen passen)
        │
        ▼
[6] ki_learning.py (nächster Cron-Lauf): misst 4h-Kurs nach Entscheidung
        │  → lerneffekt() berechnet −5…+5
        │  → ki_bewerte_lernergebnisse() lässt KI das "Warum" bewerten
        │  → speichere_regeln() schreibt Regeln mit Gewicht in ki_regeln.json
        ▼
[7] lade_lern_kontext()  (jeder neue KI-Prompt enthält die Regeln als "📌 GEWICHTETE REGELN")
        ▼
[8] skill_sync.py  (pro Cron-Lauf): ki_regeln.json Top-5 → references/aktuelle-ki-regeln.md
```

### A.2 Die 3 Depot-Säulen (isoliert voneinander)

| Säule | Anzahl | Startkapital | Risiko-Modell | Ticker-Quelle |
|-------|--------|--------------|---------------|---------------|
| Aktien | 20 Depots | je $100 (gesamt $2.000) | RISK_STUFEN 0–95 (5er-Schritte) | batch-Kandidaten (664 Aktien-Ticker) |
| ETF | 20 Depots | je $100 (gesamt $2.000) | RISK 0–95 (5er-Schritte, Stufen: Geldmarkt/Anleihen/Markt/Sektor/Thema) | etf-Kandidaten |
| Spekulation | 48 Depots | variabel (nur echte mit start>0) | Ticker-Kategorien (crypto, ai, space, lev-bull, …) | spec-Kandidaten (48 Ticker) |

→ **Gesamt investiert:** ~$7.368 (Aktien $2.052 + ETF $2.003 + Spec $3.313 laut Dashboard 01.08.)
→ **Rendite gesamt:** −16.28 % ($-1.432) — Stand 01.08. 08:39

### A.3 Börsenzeiten-Logik (`boersen.py`)

| Börse | Region | Öffnung (lokal) | Öffnung (MEZ) | Suffix-Erkennung |
|-------|--------|-----------------|----------------|------------------|
| NYSE | US | 09:30–16:00 ET | 15:30–22:00 | — |
| NASDAQ | US | 09:30–16:00 ET | 15:30–22:00 | — |
| Xetra | EU | 09:00–17:30 CE | 09:00–17:30 | `.DE` |

- Wochenende (Sa/So): alle Börsen zu → Pipeline überspringt alle Trader, nur News + Lernen
- Globale Prüfung pro Lauf (nicht pro Ticker): `ist_offen("US")` steuert spec + batch; `ist_offen("Xetra")` steuert etf
- `exchange`-Feld beim Kauf persistiert (für künftige DE/JP-Ticker vorbereitet, aktuell alle US)

### A.4 KI-Provider-Fallback (`ki_provider.py`)

Bei jedem 401/429/Timeout wird der nächste Provider probiert. **Aktuelle Kette (01.08.):**
1. `openai` — gpt-5.3-codex (nur `/v1/responses` Endpoint, **Konto leer** → sofort 429)
2. `zen` — deepseek-v4-flash-free via opencode zen → **liefert Produktiv-Calls** ✅
3. `nous-step` — stepfun/step-3.7-flash:free (Nous Portal OAuth)
4. `nous-hy3` — tencent/hy3:free (Nous Portal OAuth)
5. `openrouter` — nvidia/nemotron-3-ultra-550b-a55b:free

- Nous-OAuth-Token in `~/AppData/Local/hermes/shared/nous_auth.json`, läuft ~1h, Auto-Refresh schreibt frischen Token zurück
- Cloudflare-403 vermieden via Browser-User-Agent
- `MODEL = os.environ.get("KI_MODEL", "gpt-5.3-codex")` → konfigurierbar
- `max_tokens=1024` (vorher 512 → JSON abgeschnitten → Parsing-Fehler)

---

## TEIL B — DAS LERNEN IM DETAIL

### B.1 Lerneffekt-Skala (`ki_learning.lerneffekt()`, exakt)

| Aktion | Richtung der Bewertung | Betrag ≥3.0% | ≥2.0% | ≥1.0% | ≥0.5% | <0.5% |
|--------|------------------------|-------------|-------|-------|-------|-------|
| **kaufen** | `richtung = change` (Kursstieg = +) | +5 | +4 | +3 | +2 | 0 |
| **verkaufen** | `richtung = −change` (Kursfall = +) | +5 | +4 | +3 | +2 | 0 |
| **halten** | `richtung = −|change|` (jede Bewegung widerlegt) | −5 | −4 | −3 | −2 | 0 |

- **Schwelle 0.5 %** = Rauschen-Unterdrückung (kein Lerneffekt bei Mini-Bewegung)
- Kategorien: `wert≥3`→success, `≥1`→teilsuccess, `=0`→neutral, `≥−2`→teilfehler, sonst→fehler
- Kursentwicklung via **1h-Bars** (`yf.Ticker.history(period="3d", interval="1h")`) → nur echte Handelsstunden; keine Messung bei geschlossener Börse (sonst würde der Stand *vor* der Entscheidung gemessen)

### B.2 Echte Lerneffekt-Verteilung (`ki_log.json`, Stand 01.08.)

| Lerneffekt | Anzahl | Bedeutung |
|-----------|--------|-----------|
| +5 | 1 | deutlich bestätigt |
| +4 | 2 | klar bestätigt |
| +3 | 1 | bestätigt |
| +2 | 2 | leicht bestätigt |
| 0 | 17 | neutral (Rauschen) |
| −2 | 34 | leicht widerlegt |
| −3 | 57 | widerlegt |
| −4 | 43 | klar widerlegt |
| −5 | 27 | deutlich widerlegt |
| **Σ** | **184** | echte Lerneffekte (mit Zahl) |

→ **Positiv:** 6 (3,3 %) · **Neutral:** 17 · **Negativ:** 161 (87,5 %)
→ **Ø Lerneffekt:** −2,86 · **Trefferquote (24h):** 3,3 % (6✓ / 161✗ / 17○)
→ **Fazit:** Die KI liegt überwiegend falsch (Verkäufe zu früh, "halten" bei fallenden Titeln)

### B.3 Die 5 Lern-Dimensionen (`ki_learning.py`)

1. **News-Lernschleife** (deterministisch, KEIN KI-Call):
   - News-Score ≥75 vor Entscheidung → bei ≥2× Bestätigung: Regel "[News] Score≥75 verlässlich"
   - bei ≥2× Widerlegung: Gegen-Regel "[News] hohe Scores irreführend"
2. **Konfidenz-Kalibrierung:**
   - Gruppe hohe KI-Konfidenz (≥80) vs. niedrige (<60), je n≥3
   - Δ≥10pp → System-Erkenntnis "hohe Konfidenz verlässlich / NICHT verlässlich"
3. **Zeitfenster-Fix:** Keine Bewertung bei geschlossener Börse (1h-Bars existieren nur in Handelszeiten)
4. **Sektor-Muster:** Lerneffekte nach Sektor gruppiert (crypto, ai, space, lev-bull, lev-bear, commodity, biotech, ev, meme, index, volatility)
5. **Exit-Qualität:** `hole_verkaeufe_24h()` misst 24h nach Verkauf (1d-Bars). Ø ≥+2 % nach Verkauf, n≥2 → "Verkäufe zu früh, Take-Profit großzügiger"

### B.4 Erweiterungen P1–P5 (Stand 2026-08-01)

**P1 — Anti-Muster (Verbote):**
- `anti_muster_regeln(ergebnisse)`: gruppiert nach (Sektor, Aktion); Muster mit Ø-Lerneffekt ≤−2 und ≥2 Widerlegungen → `[Anti]`-Regel mit **negativem Gewicht**
- `speichere_regeln()`: Anti-Regeln (Präfix `[Anti]` oder `anti:True`) werden **immer behalten** (trotz Max-20-Cap durch Trennung positiv/anti)
- `lade_regeln()`: filtert Anti-Regeln nicht nach `<0.5` (Sonderbehandlung)
- `lade_lern_kontext()`: formatiert als `⚠️ VERBOT [Gewicht] [Anti] Muster → Regel`

**P2 — Opportunity-Cost:**
- `opportunity_cost_lernen(decisions)`: prüft "halten"-Entscheidungen deren Ticker danach >+3 % lief
- Schwellen: `verpasst≥2` UND `quote≥40%` → Regel "[Opp] Halt bei Aufwärts-Signal verpasst"
- Läuft bei JEDEM Lernlauf (unabhängig von neu bewerteten Decisions)
- **Echter Befund:** 79 "halten" geprüft, 4 verpasste Chancen (+3%), Ø +0,37 % → Quote 5,1 % (<40) → **keine Regel** (KI ist nicht systematisch zu vorsichtig)

**P3 — Multi-Timeframe:**
- `ki_kontext.multi_timeframe(ticker)`: yfinance 1h (letzte 2h) + 15min (letzter Tag) → "MOMENTUM: 1h +X% (Aufwärts) | 15min +Y% (Stärke)"
- Kein Extra-API-Call (yfinance wird ohnehin geladen); eingebunden in `kontext_block()` → landet im KI-Prompt

**P4 — Konzentrations-Bremse (harte Engine-Grenze):**
- `engine.ausführen()`: beim Kauf → `ticker_konzentration(ticker)` (zählt über alle 3 Depot-Typen)
- `anz ≥ 4` → Kauf blockiert, Trade `typ:"kauf_blockiert"` ins Depot-Log
- Beispiel: DOMO in 8 Depots → 🛑 BREMSE; AAPL in 1 Depot → normal gekauft

**P5 — Regel-Evolution:**
- `speichere_regeln()` → `_write_regel_snapshot()` schreibt nach `regel_history.json` (letzte 30 Snapshots: `{zeit, regeln:[{muster, gewicht, anti}]}`)
- Dashboard: Sparkline der Ø-Gewichte positiver Regeln + "N Snapshots · M Anti-Regeln"

### B.5 Prompt-Anreicherung (`ki_kontext.py`, pro Entscheidung)

Jeder KI-Prompt enthält automatisch:
1. ⚠ **Konzentration:** "BEREITS IN N DEPOTS" (≥2 Warnung, ≥4 blockt)
2. 🏭 **Sektor:** via `kategorie_fuer_ticker()`
3. 📊 **Fundamentals:** P/E, EPS, Marktkap, Marge — **24h-Cache** `fundamentals_cache.json` (kein Extra-Call pro Zyklus)
4. 🎯 **Selbst-Statistik:** "DEINE LETZTEN N ENTSCHEIDUNGEN: X% richtig, Ø Y → Qualität SCHWACH"
5. 📈 **ATR % + Vol-Ratio:** aus vorhandenen yfinance-Daten (kein Extra-Call)
6. 📈 **Multi-Timeframe:** 1h + 15min Momentum (P3)

---

## TEIL C — DIE REGELN IM DETAIL (`ki_regeln.json`, 01.08.)

**12 Regeln gesamt: 1 positiv + 11 Anti (Verbote).** Sortiert nach Gewicht:

| # | Gewicht | Muster | Regel (gekürzt) | Befund |
|---|---------|--------|-----------------|--------|
| 1 | **+0,90** | [Exit] Verkauf bei laufendem Trend | Take-Profit großzügiger (Kurs lief +4,4% weiter, n=2) | einzige positive Regel |
| 2 | −1,41 | [Anti] halten bei meme-Titeln | 2/3 widerlegt, Ø −2,0 | Verbot |
| 3 | −1,47 | [Anti] halten bei index-Titeln | 3/3 widerlegt, Ø −2,0 | Verbot |
| 4 | −1,55 | [Anti] halten bei biotech-Titeln | 2/4 widerlegt, Ø −2,5 | Verbot |
| 5 | −1,62 | [Anti] halten bei ev-Titeln | 2/3 widerlegt, Ø −2,3 | Verbot |
| 6 | −1,64 | [Anti] halten bei space-Titeln | 3/3 widerlegt, Ø −4,0 | Verbot |
| 7 | −1,67 | [Anti] halten bei commodity-Titeln | 5/6 widerlegt, Ø −2,3 | Verbot |
| 8 | −1,69 | [Anti] halten bei lev-bear-Titeln | 3/4 widerlegt, Ø −2,8 | Verbot |
| 9 | −1,69 | [Anti] halten bei ai-Titeln | 5/5 widerlegt, Ø −3,2 | Verbot |
| 10 | −1,82 | [Anti] halten bei crypto-Titeln | 6/6 widerlegt, Ø −3,3 | Verbot |
| 11 | −1,86 | [Anti] halten bei lev-bull-Titeln | 5/5 widerlegt, Ø −4,0 | Verbot |
| 12 | −1,88 | [Anti] halten bei volatility-Titeln | 3/3 widerlegt, Ø −4,3 | Verbot |

**Erkenntnis:** Der systematische Fehler ist "**halten**" bei spekulativen Titeln (Hebel-ETFs, Krypto, Meme) die danach weiter fallen. Die KI lernt fast nur Verbote, weil die Gesamt-Trefferquote niedrig ist.

---

## TEIL D — SKILL-FÜTTERUNG IM DETAIL

### D.1 Drei Mechanismen

**M1 — Automatischer Sync (`skill_sync.py`, pro Cron-Lauf):**
- Liest `ki_regeln.json`, sortiert nach Gewicht, nimmt Top-5 (`MAX_REGELN=5`)
- Schreibt Markdown nach `~/AppData/Local/hermes/skills/ki-trading-learning-loop/references/aktuelle-ki-regeln.md`
- 3 Sektionen: ⭐ Bestätigte Regeln · ⚠ Widerlegte Muster (Verbote) · 📊 Status der Lern-Schleife (Trefferquote, Ø-Lerneffekt, Sektor-Bilanz aus `ki_log.json` letzte 7 Tage)
- Loggt "Skill-Sync: N Regeln in Skill übernommen"

**M2 — Prompt-Einspeisung (`lade_lern_kontext()`):**
- Lädt Regeln + Notizen aus `ki_log.json`
- Formatiert als "📌 GEWICHTETE REGELN (aus Lern-Erfahrung)" mit ⭐/⚠-Präfixen
- Wird in **jeden** KI-Entscheidungs-Prompt gereicht → die KI "weiß" beim nächsten Mal was bisher funktioniert hat

**M3 — Struktur-Update (manuell via `skill_manage`):**
- Bei Systemänderungen (neue Module, Pitfalls, Dateien-Tabelle) patcht der Assistent die Haupt-`SKILL.md`
- `references/` enthält zusätzlich: Session-Summaries, Lerneffekt-Schema, Call-JSON-Patterns, Dashboard-Feature-Doku

### D.2 Der Hermes-Skill als persistenter Speicher

Der Skill `ki-trading-learning-loop` überlebt Kontext-Kompaktierungen des Chats (wird bei jedem neuen Turn neu geladen). Struktur:
```
ki-trading-learning-loop/
├── SKILL.md                          # Architektur, Dateien, Pitfalls, P1–P5, Prompt-Anreicherung
└── references/
    ├── aktuelle-ki-regeln.md         # ← Cron-Sync (Top-5 Regeln + Status)
    ├── 2026-08-01-ki-verbesserungen-p1-p5.md
    ├── 2026-07-31-session-summary.md
    ├── dashboard-features-abc.md
    ├── ki-call-json-patterns.md
    ├── ki-reflexion.md
    └── lerneffekt-schema.md
```

### D.3 Was die Skill-Sync-Datei konkret enthält (Beispiel 01.08. 12:24)

```markdown
# Aktuelle KI-Regeln (Stand 01.08.2026 12:24)
Die 5 stärksten Regeln aus der KI-Lern-Bewertung (ki_regeln.json), automatisch per Cron synchronisiert:

## ⭐ Bestätigte Regeln (Handlungs-Regeln)
### 1. ⭐ Gewicht 0.9
- Muster: [Exit] Verkauf bei laufendem Trend
- Regel: Verkäufe kommen zu früh – Kurs lief nach Verkauf im Schnitt +4.4% weiter (n=2)…

## ⚠ Widerlegte Muster (was die KI NICHT tun soll)
### 1. ⛔ Gewicht -1.82
- Muster: [Anti] halten bei crypto-Titeln
- Regel: NICHT halten bei crypto-Titeln – systematisch falsch (6/6 widerlegt, Ø -3.3)…
```

---

## TEIL E — TRADE-BREMSEN (Engine-Ebene, `engine.ausführen`)

| Bremse | Bedingung | Verhalten |
|--------|-----------|-----------|
| Konfidenz | <40 | keine Aktion |
| Bargeld | <$1 | kein Kauf |
| Penny | Kurs <$1,00 | übersprungen (außer Spec) |
| VIX | >22 | Käufe gesperrt |
| Drawdown | >30 % | Depot gesperrt |
| **Konzentration (P4)** | **Ticker in ≥4 Depots** | **Kauf blockiert** |
| Budget-Bonus | teure Aktie | `score += 15*(1-preis/budget)` |

→ Die **Trader-Bremsen sind hart** (Python), die **KI-Regeln sind weich** (nur Prompt-Einfluss). Hybrider Ansatz.

---

## TEIL F — OFFENE PUNKTE / NICHT IMPLEMENTIERT

| Punkt | Status | Detail |
|-------|--------|--------|
| `ki_reflexion.py` | **geschrieben, NICHT in Pipeline** | 19KB, `selbst_reflexion()` analysiert Verlust-Aversion, Regel-Abweichungen, Grund-Muster. Läuft nie automatisch. |
| Skill-Sync um Fortschritt | nur Regeln | `aktuelle-ki-regeln.md` zeigt Regeln + Status, aber keinen **Trend** (Trefferquote-Verlauf über Zeit) |
| Regel-Decay sichtbar | unsichtbar | Decay 4,3 Tage Halbwert läuft automatisch, keine Anzeige im Dashboard, kein manuelles Pinning |
| Cross-Depot-Lernen | fehlt | Aktien/ETF/Spec lernen isoliert, kein Portfolio-Level-Transfer |
| SKILL.md auto-Update | manuell | Nur `references/`, nicht Haupt-SKILL.md (veraltet auf "Stand 2026-07-31") |
| Port 5200/5299 | blockiert | Zombie-Prozesse ohne Admin-Kill → Dashboard auf 5300 |

---

## TEIL G — FÜR EINE ANDERE KI: KOMPAKT-BEwertung

**Was das System kann (✅):**
- Autonomes Papier-Trading mit LLM-Entscheidungen + Provider-Fallback bei Ausfall
- Differenziertes Lernen (−5…+5 statt binary) mit Rauschen-Unterdrückung <0,5 %
- Selbst-Korrektur via Anti-Regeln (Verbote) + Opportunity-Cost-Analyse
- Automatischer Skill-Transfer (Regeln → Hermes-Skill → nächster Prompt)
- Multi-Timeframe + Fundamentals + News-Sentiment im Prompt
- Harte Risiko-Bremsen (Drawdown, VIX, Konzentration, Penny)
- Börsenzeiten-bewusste Pipeline

**Was es NICHT kann (❌):**
- Echte Gewinne erzielen (aktuell −16 %, KI liegt in 87 % der Fälle falsch)
- Echtgeld-Orders (rein papierbasiert)
- Über Depot-Grenzen hinweg lernen (isoliert)
- `ki_reflexion.py` nutzen (noch nicht live)

**Hybrider Kern:** Harte Trader-Bremsen (deterministisch, Python) + weiche KI-Regeln (LLM-Prompt-Einfluss). Die KI entscheidet, der Trader hat das letzte Wort bei Risiko.
