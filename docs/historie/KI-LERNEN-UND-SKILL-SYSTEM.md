# Micro-Trader — KI-Lernen & Skill-Fütterung (Technische + Inhaltliche Zusammenfassung)

**Stand:** 01.08.2026 · **System:** Windows 11, Python 3.12, yfinance, Hermes-Skill, Flask-Dashboard (Port 5300)
**Zweck dieses Dokuments:** Eine andere KI (oder Entwickler) soll verstehen, WAS das System lernt, WIE es lernt, und WIE der Hermes-Skill automatisch mitgefüttert wird.

---

## 1. Architektur-Überblick

```
Trader (batch_trader / etf_trader / spec_trader)
   │  sammelt Marktdaten (Kurs, RSI, SMA20/50, VIX, News, Bargeld, Regeln)
   ▼
KI-Entscheidung (ki_decisions.py → ki_provider.py → LLM)
   │  Output: {ticker, aktion:kaufen|halten|verkaufen, konfidenz, grund}
   ▼
Trader führt aus (engine.py ausführen) — NUR wenn Bremsen passen
   │  (Konfidenz<40 → nichts, Bargeld<1$ → kein Kauf, VIX>22 → gesperrt,
   │   Drawdown>30% → Depot gesperrt, Penny<1$ → übersprungen,
   │   P4: Ticker bereits in ≥4 Depots → Kauf blockiert)
   ▼
ki_learning.py (alle 3 Min via Cron-Pipeline)
   │  misst Kursentwicklung nach Entscheidung (1h/4h/24h-Bars)
   │  berechnet Lerneffekt (−5…+5), lässt KI das "Warum" bewerten
   │  speichert Regeln mit Gewicht → ki_regeln.json
   ▼
skill_sync.py (pro Cron-Lauf)
   │  Top-5 Regeln → Hermes-Skill references/aktuelle-ki-regeln.md
   ▼
lade_lern_kontext() speist dieselben Regeln in JEDEN nächsten KI-Prompt
   ▼
Hermes-Skill "ki-trading-learning-loop" = persistente Wissensbasis
```

**Depots:** 20 Aktien-Depots (à $100) + 20 ETF-Depots (Risiko 0–95) + 48 Spekulations-Depots (Start je nach Ticker, echte Depots). Reines Papier-Trading (yfinance-Kurse, keine echten Orders).

**Börsenzeiten:** US 15:30–22:00 MEZ, Xetra 09:00–17:30 MEZ. Wochenende + geschlossene Börsen → nur News-Sammlung + Lernen, keine Trades. Pipeline prüft global pro Lauf.

**KI-Provider-Kette** (Fallback, in `ki_provider.py`):
`openai (gpt-5.3-codex, nur Responses-Endpoint, Konto leer)` → `zen (deepseek-v4-flash-free, liefert Produktiv)` → `nous-step (stepfun)` → `nous-hy3 (tencent)` → `openrouter (nemotron)`. Bei jedem Fehler wird der nächste probiert.

---

## 2. KI-Lernen — Technisch

### 2.1 Lerneffekt-Skala (−5…+5)
Nach jeder Entscheidung wird die **tatsächliche Kursentwicklung** gemessen (nur bei offener Börse, echte Handelsstunden via 1h-Bars):
- ≥ +3.0 % in Richtung der Entscheidung → **+5** (deutlich bestätigt)
- ≥ +2.0 % → **+4** · ≥ +1.0 % → **+3** · ≥ +0.5 % → **+2**
- < +0.5 % (Rauschen) → **0** (kein Lerneffekt)
- Vorzeichen folgt der Richtung (Kauf + Kurs steigt = +, Verkauf + Kurs fällt = +)
- Kategorien: ✅ success / 🟡 teilsuccess / 🧠 neutral / 🔻 teilfehler / ❌ fehler

### 2.2 Die 5 Lern-Dimensionen (`ki_learning.py`, Stand 2026-07-31)
1. **News-Lernschleife** (deterministisch, kein KI-Call): News-Score ≥75 vor Entscheidung → bei ≥2× Bestätigung Regel "[News] Score≥75 verlässlich", bei ≥2× Widerlegung Gegen-Regel.
2. **Konfidenz-Kalibrierung:** Trefferquote bei KI-Konfidenz ≥80 vs. <60, n≥3, Δ≥10pp → "hohe Konfidenz verlässlich / NICHT verlässlich".
3. **Zeitfenster:** Keine Bewertung bei geschlossener Börse (keine neuen Bars → Messung verfälscht).
4. **Sektor-Muster:** Lerneffekte werden nach Sektor gruppiert (crypto, ai, space, lev-bull, …).
5. **Exit-Qualität:** 24h nach Verkauf gemessen (1d-Bars). Ø ≥+2 % nach Verkauf, n≥2 → "Verkäufe zu früh, Take-Profit großzügiger".

### 2.3 Erweiterungen P1–P5 (Stand 2026-08-01)
- **P1 Anti-Muster:** `anti_muster_regeln()` findet Muster mit Ø-Lerneffekt ≤−2 und ≥2 Widerlegungen → speichert sie als **[Anti]-Regeln mit negativem Gewicht** (Verbote). `speichere_regeln()` behält Anti-Regeln immer (trotz Top-20-Cap). `lade_lern_kontext()` formatiert sie als "⚠ VERBOT" im Prompt.
- **P2 Opportunity-Cost:** `opportunity_cost_lernen()` prüft "halten"-Entscheidungen deren Ticker danach >+3 % lief → verpasste Chance → Regel "[Opp] Halt bei Aufwärts-Signal verpasst".
- **P3 Multi-Timeframe:** `ki_kontext.multi_timeframe()` liefert 1h + 15min-Momentum aus yfinance (kein Extra-Call) → besseres Timing im Prompt.
- **P4 Konzentrations-Bremse:** `engine.ausführen()` blockiert Käufe wenn Ticker bereits in ≥4 Depots (`ticker_konzentration()` aus `ki_kontext`). Harte Engine-Grenze, nicht nur Prompt-Warnung.
- **P5 Regel-Evolution:** `speichere_regeln()` schreibt bei jedem Lauf einen Snapshot nach `regel_history.json` (letzte 30). Dashboard zeigt Sparkline der Ø-Regelgewichte.

### 2.4 Prompt-Anreicherung (`ki_kontext.py`)
Jeder KI-Entscheidungs-Prompt enthält automatisch:
- ⚠ Konzentrations-Warnung ("BEREITS IN N DEPOTS")
- 🏭 Sektor (via `kategorie_fuer_ticker`)
- 📊 Fundamentals (P/E, EPS, Marktkap, Marge — 24h-Cache `fundamentals_cache.json`, kein Extra-Call)
- 🎯 Selbst-Statistik ("DEINE LETZTEN N ENTSCHEIDUNGEN: X% richtig, Ø Y → Qualität SCHWACH")
- 📈 ATR % + Volumen-Ratio (aus vorhandenen yfinance-Daten)
- 📈 Multi-Timeframe-Momentum (P3)

---

## 3. Skill-Fütterung — Technisch

### 3.1 Drei Mechaniken
1. **Automatisch pro Cron-Lauf (`skill_sync.py`):** Liest `ki_regeln.json` (Top-5 nach Gewicht), schreibt sie als Markdown nach `references/aktuelle-ki-regeln.md` im Hermes-Skill-Ordner. Enthält: bestätigte Regeln (⭐) + widerlegte Muster (⚠ Verbote).
2. **Prompt-Einspeisung (`lade_lern_kontext()`):** Dieselben Regeln werden als "📌 GEWICHTETE REGELN" in jeden KI-Entscheidungs-Prompt gereicht → die KI "weiß" beim nächsten Mal, was bisher funktioniert hat.
3. **Struktur-Updates (manuell via `skill_manage`):** Bei Systemänderungen (neue Module, Pitfalls, Dateien-Tabelle) patcht der Assistent die Haupt-`SKILL.md` des Skills.

### 3.2 Der Skill als persistenter Speicher
Der Hermes-Skill `ki-trading-learning-loop` überlebt Kontext-Kompaktierungen des Chats. Er enthält:
- `SKILL.md` — Architektur, Dateien-Tabelle, Pitfalls, Prompt-Anreicherung, P1–P5-Sektion
- `references/aktuelle-ki-regeln.md` — die Top-5 live gelernten Regeln (Cron-Sync)
- `references/*.md` — Session-Summaries, Lerneffekt-Schema, Call-JSON-Patterns, Dashboard-Feature-Doku

### 3.3 Cron-Pipeline
Hermes-Cron alle 3 Min → `micro-trader-pipeline.py` (detached, Py312-Pin, `CREATE_NO_WINDOW`) → ruft nacheinander auf:
`news_monitor.py` → `ki_news.py` (KI bewertet News) → `spec_trader.py` (US offen) → `etf_trader.py` (Xetra offen) → `batch_trader.py` (US offen) → `ki_learning.py` → `skill_sync.py`.

---

## 4. Inhaltlich: WAS die KI lernt (konkrete Befunde)

**Echte Metriken (Stand 01.08.2026):**
- 184 Entscheidungen bewertet, 12 Regeln gelernt (1 positiv + 11 Anti/Verbote)
- Trefferquote (24h): **3.3 %** (6✓ / 161✗ / 17○) — **sehr schwach**
- Ø Lerneffekt: **−2.86** (Skala −5…+5) — KI liegt mehrheitlich falsch
- Gesamt-Rendite: **−16.28 %** ($-1.432 auf ~$7.368)

**Was die KI gelernt hat (Beispiele aus `ki_regeln.json`):**
- ✅ "[Exit] Verkauf bei laufendem Trend → Take-Profit großzügiger" (G 0.82)
- ⚠ "[Anti] halten bei crypto-Titeln → NICHT halten, 6/6 widerlegt, Ø −3.3"
- ⚠ "[Anti] halten bei lev-bull-Titeln → NICHT halten, 5/5 widerlegt, Ø −4.0"
- ⚠ "[Anti] halten bei volatility-Titeln → NICHT halten, 3/3 widerlegt, Ø −4.3"
- ⚠ "[Anti] halten bei ai/space/commodity-Titeln → systematisch falsch"

**Erkenntnis:** Die KI lernt fast ausschließlich **Verbote** (was sie lassen soll). Positive "Tu-dies"-Regeln sind rar, weil die Trefferquote generell niedrig ist. Der Hauptfehler: "halten" bei spekulativen Titeln, die danach weiter fallen.

**Die KI-Entscheidungen sind deterministisch regelbasiert, aber das *Warum* wird von einem LLM bewertet** — das System ist ein hybrider Ansatz: harte Trader-Bremsen (Python) + weiche KI-Regeln (LLM-Prompts).

---

## 5. Offene Punkte / Nicht implementiert

- **P6–P10 (geplant, nicht gebaut):** Skill-Sync um Lern-Fortschritt erweitern · `ki_reflexion.py` (19KB, existiert, läuft NICHT in Pipeline) integrieren · Regel-Decay sichtbar/manuell · Cross-Depot-Lernen · SKILL.md auto-Update.
- `ki_reflexion.py` (`selbst_reflexion()`) ist geschrieben aber **nicht in der Cron-Pipeline aktiv** — verschwendetes Potenzial.
- Port 5200/5299 durch Zombie-Prozesse blockiert (kein Admin-Kill) → Dashboard läuft auf 5300.
- Positive Regeln fast absent → KI ist zu pessimistisch (Opportunity-Cost zeigt: nur 5% verpasste Chancen, also eigentlich nicht zu vorsichtig — das "Verbots"-Bias kommt aus den vielen Hebel/Short-ETFs die systematisch scheitern).

---

## 6. Für eine andere KI: Was hier "geht"

✅ Autonomes Papier-Trading mit LLM-Entscheidungen (Fallback-Kette bei Provider-Ausfall)
✅ Differenziertes Lernen mit −5…+5 Skala statt binary richtig/falsch
✅ Selbst-Korrektur via Anti-Regeln (Verbote) + Opportunity-Cost
✅ Automatische Skill-Fütterung (Regeln → Hermes-Skill → nächster Prompt)
✅ Multi-Timeframe + Fundamentals + News-Sentiment im Prompt
✅ Harte Risiko-Bremsen auf Engine-Ebene (Drawdown, VIX, Konzentration, Penny)
✅ Börsenzeiten-bewusste Pipeline (kein sinnloses Traden außerhalb der Handelszeit)

❌ Echte Gewinne (aktuell −16% — das System lernt, ist aber noch schwach)
❌ Echtgeld-Orders (rein papierbasiert)
❌ Cross-Depot-Portfolio-Lernen (Depots isoliert)
❌ `ki_reflexion.py` noch nicht live
