# Micro-Trader — Ultra-Detail-Zusammenfassung für KI-Modelle

**Zweck:** Vollständiger, faktischer IST-Stand für eine unabhängige KI, die dieses Projekt
übernehmen/erweitern soll. Alle Angaben aus live laufendem Code extrahiert (2026-08-02, v2.7.0).

---

## 0. TL;DR

- **Was:** Autonomes Paper-Trading-System (Aktien/ETF/Spekulation) mit KI-Entscheidungen + selbstlernendem Regelsystem.
- **Sprachen:** Python 3.12 (Backend/Engine/KI) + Vanilla-JS (Dashboard, kein Framework).
- **Runtime:** `C:\Program Files\Python312\python.exe` — **NICHT** Hermes-venv.
- **Dashboard:** Flask, Port **5300**, Auto-Refresh 30s. Version-Badge im Header.
- **Cron:** Hermes Job `c0e89575d724` (15min, `--mode ki`) → `micro-trader-cron.py`.
- **Settings:** 32 Felder in 7 Kategorien, mit Risikowarnung + Bestätigung.
- **Regel #1:** Backup vor jeder Änderung (`backup.py before/after/restore`).

## 1. System-Architektur

```
CRON (15min) → micro-trader-cron.py --mode ki
  └─ micro-trader-pipeline.py --mode ki
       ├─ news_monitor.py     (RSS sammeln)
       ├─ ki_news.py          (KI-News-Bewertung + VORFILTER)
       ├─ spec_trader.py      (48 Spec-Entscheidungen)
       ├─ ki_decisions.py     (KI-Entscheidungen + Caps/Swaps/R1/R3)
       ├─ ki_learning.py      (Lernmodul: Regeln, Scores, Kalibrierung)
       └─ skill_sync.py       (Regeln → Hermes-Skill)
Engine-Cron (5min, KEIN LLM): boersen.py, engine.py, trader.py
                              → Ausführung, Bremsen, Stop-Loss/TP
Dashboard.py (5300) ← liest JSON-State + ki_log.json → 9 Tabs
```

**Datenfluss Lernen:**
`KI-Entscheidung → ki_log.json → Engine misst Kurs (4h/1d/1w) → lerneffekt −5…+5 →
ki_learning.analysiere_entscheidungen → Regeln → learned_rules.json → nächster KI-Prompt + Skill-Sync`

## 2. Module (Funktionen + Settings-Bindung)

| Modul | LOC | Kernfunktionen | Settings-Bindung |
|-------|-----|----------------|------------------|
| `ki_decisions.py` | 571 | `entscheide_ticker`, `entscheide_spec_batch`, `entscheide_aktien_depot`, `news_fuer_ticker`, `hole_vix` | `ki.konfidenz_cap`, `ki_temperatur`, `news_swap_min_score` (via `_ki_set`) |
| `ki_learning.py` | 1921 | `lerneffekt`, `lerneffekt_multiskalen`, `multi_timeframe_regel_lernen`, `news_swap_score`, `anti_muster_regeln`, `analysiere_entscheidungen`, `cross_depot_lernen` | `lernen.anti_min_n` |
| `learned_rules.py` | 490 | `lade_regeln` (Decay-Sort), `speichere_regeln`, `decay_lambda_global`, `finde_konflikte`, `lebenszyklus_status` | `lernen.decay_lambda` |
| `engine.py` | 570 | `Depot`-Klasse, `scan_markt`, `bewerte`, `signal_aktion`, `ausführen` (Konzentrations-Bremse) | `engine_bremsen.max_depot_pro_ticker`, `drawdown_sperre_prozent` |
| `trader.py` | 560 | `berechne_indikatoren`, `Depot`-Klasse, `RISK`-Profile | `risk_parameter.moderate/aggressive_*` |
| `spec_trader.py` | 240 | `SpecDepot`, `fetch_analyse`, `ausführen` | `depot_struktur.max_spec_depots` |
| `spec_watch.py` | 280 | 48-Ticker-Watchlist (14 Kategorien) | — |
| `ki_news.py` | 390 | `ist_irrelevant` (VORFILTER), `classify_headline`, `ki_bewerte_news`, `news_analyse` | — |
| `settings_loader.py` | 274 | `lade_settings`, `validiere_und_risiko`, `speichere_settings`, `LABELS` (32 Felder), Helfer `ki()/lernen()/bremse()/kapital()/depot_struktur()/risk_param()` | — |
| `dashboard.py` | 834 | Flask + 12 Routen + `boersen_chips()`, `renderSettings`, `settingsInput` | `news.news_min_score` |
| `dashboard.html` | 1932 | Vanilla-JS UI (Glassmorphism), 9 Tabs, C-Tabs Settings, Erklärungen | — |
| `backup.py` | 140 | `before/after/list/restore/rollback` | — |
| `boersen.py` | 147 | `boerse_fuer_ticker`, `BOERSEN`, `ist_offen`, `offene_boersen` | — |

**State-Files:** `ki_log.json` (220KB), `learned_rules.json` (16KB), `settings.json`,
`news_cache.json`, `regel_history.json` (50KB), `system_log.json` (80KB), `depot_XXX.json` (20×),
`etf_XXX.json` (20×), `spec_depots/*.json` (48×).

---

## 3. Optik & Dashboard-Layout (Vanilla-JS, Glassmorphism, hell)

**Design:** Helles Apple/Glassmorphismus (seit v2.8.0 PV-Optik-Transfer). 
- Font: Inter + SF Pro Fallback, tabular-nums für Zahlen, font-smoothing:antialiased
- Farben: --accent #0A84FF (Apple Blau), --green #30D158, --red #FF453A, --text #1C1C1E
- Glas: backdrop-filter blur(24px) saturate(180%) + Glas-Kante (border + ::after edge2), shadow-lg
- Hintergrund: linear-gradient(160deg #F5F7FA→#EAF0F7) + radial Glows (blau/grün, fixed)
- Tabs/iOS-Segmented: BG rgba(118,128,.10), aktiver Tab weiß mit Schatten, Pills radius 999px
- Sticky Topbar (blur20), Motion cubic-bezier(.32,.72,0,1)
- KEIN Dark Mode (hart vorgegeben)
Kein Dark Mode (User-Wunsch). Responsive via CSS-Grid.

### 3.1 Header (oben, fix)
- Logo (3-Balken: grün/gelb/rot) + "Micro-Trader"
- Datum/Zeit + Portfolio-Info (`20 Aktien · 20 ETF · 48 Spek`)
- **Markt-Chips** (neu v2.7.0): statt Textzeile nun **Chips** mit flex-wrap.
  Nur Börsen mit echten Positionen: `🔴 NYSE/NASDAQ 100%` (Wert-Anteil % im Portfolio).
  Crypto → `🪙 Crypto 24/7`. Kein Chip, wenn kein Titel an der Börse.
- Version-Badge: `🔔 v2.7.0 · 2026-08-02 20:45 · Chips & Clarity` (Hover = letzte 3 Changelog)
- Notification-Bell (🔔, rot bei neuen Warnungen)

### 3.2 Tabs (9 Haupt-Tabs)
| Tab | Inhalt | Optik |
|-----|--------|-------|
| 📊 Übersicht | Hero + Depot-Cards pro Risikostufe, Gesamtwert/Rendite, KI-letzte, Cron-Status | Glass-Cards, Gradient-Hero |
| 📈 Aktien | 20 Risikostufen als Grid, Detail-Modal mit Chart.js + News-Impact + KI-Entscheidung | Card-Grid, CSS-Bars |
| 📦 ETF | 6 Risikostufen (Geldmarkt→Gehebelt), MaxDD, Fortschrittsbalken | Table + Bars |
| 🔥 Spekulation | 3 Subtabs: Übersicht/Positionen/Watchlist, 48 Ticker, Kategorie-Filter, Mini-Charts | Tabs-in-Tab, Pills |
| 📊 Analyse | Top-Ticker + Grund-Statistik (Trefferquote pro Begründung) | CSS-Bars |
| 📰 News | KI-bewertet (Score ≥ `news_min_score`), irrelevant rausgefiltert | Glass-Cards |
| 🤖 KI-Log | 6 Subtabs: Auswertung/Entscheidungen/News/Lerneffekte/Regeln/**Was die KI lernt** | Live-Daten aus ki_log + learned_rules |
| 📋 Log | system_log.json chronologisch | Monospace |
| ⚙️ Einstellungen | 7 C-Tabs (siehe 3.3) | Glass-Panels |

### 3.3 Settings-Tab (⚙️) — C-Tabs + kompakt + erklärt
**7 Unter-Tabs:** 🤖 KI · 🧠 Lernen · 💰 Kapital · 📊 Depot · 🎚️ Risk · 🛡️ Bremsen · 📰 News
- **2-Spalten-Raster** pro Tab (Felder nebeneinander, klein: 11px)
- **Natürliche Namen** statt Technik-Pfad (z.B. "Max. Selbstvertrauen der KI" statt `konfidenz_cap`)
- **Erklärung** unter jedem Feld (1–2 Sätze, Layman-verständlich, aus `settings_loader.LABELS`)
- **Empfohlen-Bereich** als "⚖ 40–90%"
- **Tab-Einleitung** (TAB_INTRO) pro Kategorie
- **Sicherheitsnetz:** harte MIN/MAX → Speichern blockiert; empfohlener Bereich → `confirm()`-Dialog "⚠️ RISIKOWARNUNG" vor Speichern
- **Reset Defaults**-Button (eigene Bestätigung)

## 4. Settings-System (32 Felder, 7 Kategorien)

| Kategorie | Felder (Default) | Risikowarnung bei |
|-----------|------------------|-------------------|
| `ki` | konfidenz_cap(60), ki_temperatur(0.1), min_konfidenz_kaufen(60), exit_score_schwelle(70), news_swap_min_score(75), news_swap_aktiv(true), multi_timeframe_lernen(true) | cap<40, temp>0.3 |
| `lernen` | decay_lambda(0.01), anti_min_n(5), anti_min_widerlegt_pct(60), max_regeln(40), lern_modus(auto) | decay>0.03, anti_n<3 |
| `kapital` | gesamt_budget(10000), aktien_anteil(40), etf_anteil(30), spec_anteil(30), max_gesamt_drawdown(25) | aktien>60, drawdown<15 |
| `depot_struktur` | aktien_stufen(20), aktien_schritt(5), max_spec_depots(48), etf_stufen_aktiv([6]) | stufen>20, spec>60 |
| `risk_parameter` | moderate(pos0.35/sl0.92/tp1.12), aggressive(pos0.50/sl0.85/tp1.20) | sl zu eng/weit, pos zu groß |
| `engine_bremsen` | max_depot_pro_ticker(4), drawdown_sperre_prozent(30), wochenende_handel(false) | konz>8, drawdown<15 |
| `news` | news_min_score(20), news_max_alter_std(48) | score<10 |

**API:** `GET /api/settings` (settings+limits+bools+labels), `POST /api/settings` (validiert+speichert, `bestaetigt:true` bei Warnung).
**Loader:** `settings_loader.py` (Fallback-Hardcoded bei Fehler).

## 5. Lern-System (7 Mechanismen)

| # | Mechanismus | Quelle | Anwendung |
|---|-------------|--------|-----------|
| 1 | Anti-Regeln | `anti_muster_regeln()` | Muster systematisch falsch → Verbot (Prompt-Constraint) |
| 2 | Swap-Regeln | `swap_score_berechnen()` | Halte-Position schlechter als Benchmark → Umschichtung |
| 3 | Konfidenz-Cap | `konfidenz_kalibrierung()` | KI-Konfidenz gedrosselt (60) bei Selbstüberschätzung |
| 4 | Exit-Score | `exit_score_berechnen()` | Trend intakt + Verkauf-Wunsch → "halten" (Score≥70) |
| 5 | News-Swap | `news_swap_score()` | News≥75 + schwach → "verkaufen" (Score≥60) |
| 6 | Multi-Timeframe | `multi_timeframe_regel_lernen()` | 15min↑/1d↓ Divergenz → Anti/Positiv-Regel |
| 7 | Konzentrations-Lernen | `cross_depot_lernen()` | Ticker in ≥4 Depots → Anti-Regel "streuen" |

**Governance (R3):** Engine-Bremsen (hart) > Meta-Cap > News-Swap (News≥75) > Exit-Score > KI.
Konflikt (Exit-Score=halten vs News-Swap=verkaufen) → **News-Swap gewinnt**, vermerkt als `regel_konflikt` im ki_log.

**Decay (R2):** `lade_regeln()` sortiert nach `effektiv_gewicht` (gewicht × exp(-decay_lambda × tage)), nicht nach `gewicht`.
**Regeln im Prompt (R1):** `ki_decisions` baut "GELERNTE REGELN"-Block + schreibt `angewandte_regeln` ins ki_log.
**Ausreißer-Schutz (R5):** Anti-Regeln ab `anti_min_n=5` Samples, ≥60% Widerlegung.

---

## 6. Bekannte Fallen (für künftige KI-Arbeit — kritisch!)

### 6.1 Venv-Kontamination im Cron
**Symptom:** `ModuleNotFoundError` / falsche Packages im Cron-Lauf.
**Ursache:** Hermes-venv in `PYTHONPATH`/`PYTHONHOME`.
**Fix:** `micro-trader-cron.py` entfernt beide vor Subprozess. Manuell: `env -u PYTHONPATH -u PYTHONHOME`.

### 6.2 Dashboard-Port 5300 Zombie-Prozesse
**Symptom:** `curl localhost:5300/data` liefert **alte/veraltete Daten** (Code-Änderung nicht sichtbar).
**Ursache:** Mehrfache `dashboard.py 5300`-Starts → nur einer bindet, curl trifft den alten.
**Diagnose:** PowerShell `Get-CimInstance Win32_Process` mit `CommandLine like '*dashboard*5300*'`.
**Fix:** `MSYS_NO_PATHCONV=1 taskkill /F /PID <pid>` für alle außer gewünschtem.
**Verifikation:** `curl /data` → `ki_lern_notizen > 0`, `konfidenz_cap: 60`.

### 6.3 JSON-Corruption in `ki_log.json`
**Symptom:** `json.JSONDecodeError` beim Laden.
**Ursache:** Concurrent Writes (Engine + KI parallel) ohne Lock.
**Fix:** `ki_decisions.schreibe_ki_log` nutzt `threading.Lock`. Bei Corruption: letzte valide Zeile behalten.

### 6.4 Decay wurde ignoriert (R2, behoben)
`lade_regeln` sortierte nach `gewicht` statt `effektiv_gewicht` → behoben.

### 6.5 Regeln wirkten nicht (R1, behoben)
`learned_rules` nicht im `ki_decisions`-Prompt → behoben (GELERNTE REGELN-Block + `angewandte_regeln`).

## 7. Regel #1: Backup vor jeder Änderung

**Helfer:** `backup.py` (im Projekt-Root).
```bash
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py before "<desc>"  # snapshot
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py after  "<desc>"  # nach Verifikation
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py list              # alle Snapshots
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py restore <id|idx>  # Rollback
```
- Snappt alle `*.py/*.json/*.html/*.md` (außer Logs >5MB: ki_log/spec_log/system_log) nach `backups/<TS>__<DESC>/`.
- Restore: 1:1 `shutil.copy2`, danach Modul-Import testen + Dashboard-Neustart (Port-Zombie beachten!).
- **Aktueller Stand:** 3 Backups vorhanden (v2.6.0 Basis → v2.7.0 after), Regel #1 wird seit 2026-08-02 19:25 strikt befolgt.

## 8. Version-Log (Changelog)

`version.json` (Single Source of Truth) → Header-Badge via `/api/version`.

| Version | Datum | Codename | Kern |
|---------|-------|----------|------|
| **2.7.0** | 2026-08-02 20:45 | Chips & Clarity | Markt-Chips (nur reale Börsen + %-Anteil) · Settings mit natürlichen Namen + Erklärungen |
| 2.6.0 | 2026-08-02 19:30 | Compact Settings | Settings als C-Tabs + 2-Spalten-Raster, kompakt |
| 2.5.0 | 2026-08-02 18:45 | Financial Settings | Finanz-Settings (Kapital/Depot/Risk) an trader.py + spec_trader.py gebunden |
| 2.4.0 | 2026-08-02 18:15 | Settings & Safety | Settings-Tab + Risikowarnung + Backup-System + R1–R5 |
| 2.3.0 | 2026-08-02 12:57 | Governance | R1–R5 Bestandshärtung |
| 2.2.0 | 2026-08-01 14:30 | Learning Deep | KI-Lern-Tab, News-Filter Vor+Nach |
| 2.1.0 | 2026-08-01 09:00 | Tabs & Transparency | News-Impact, Drawdown-Warnung, Cap-Badge |

**Bump-Regel:** Bei jeder abgeschlossenen Änderung `version.json` hochzählen + Changelog.

## 9. Quick-Start für künftige KI-Session

```bash
cd /c/Users/goldi/projects/micro-trader
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py before "meine aenderung"
# ... ändern ...
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" dashboard.py 5300   # (alten Port-5300-Prozess zuerst killen!)
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py after  "meine aenderung"
```
**Verify:** Modul-Import ok · `curl /data` frisch · Cron-Lauf ohne Fehler (`tail cron_pipeline.log`).

## 10. Datei-Index (Top-Module)

| Datei | LOC | Rolle |
|-------|-----|------|
| `ki_learning.py` | 1921 | Lern-Engine (Regeln, Scores, Kalibrierung) |
| `ki_decisions.py` | 571 | KI-Entscheidungen + Caps/Swaps/R1/R3 |
| `learned_rules.py` | 490 | Regelbasis CRUD + Status + Konflikte |
| `engine.py` | 570 | Trading-Engine (Bremsen, Ausführung) |
| `trader.py` | 560 | Basis-Trader (Indikatoren, Depot, RISK) |
| `spec_trader.py` | 240 | Spekulations-Logik |
| `spec_watch.py` | 280 | 48-Ticker-Watchlist (14 Kategorien) |
| `ki_news.py` | 390 | News-Bewertung + VORFILTER |
| `settings_loader.py` | 274 | Settings-Validierung + Risiko + LABELS |
| `dashboard.py` | 834 | Flask + 12 Routen + boersen_chips |
| `dashboard.html` | 1932 | Vanilla-JS UI (Glassmorphism) |
| `backup.py` | 140 | Backup-Helper (Regel #1) |
| `boersen.py` | 147 | Börse-Mapping (Ticker→Exchange) |

**Zentrale Doku:** `README.md` (projekt-Root) + Sync nach `~/AppData/Local/hermes/skills/ki-trading-learning-loop/references/PROJEKT-README.md`.
**Skill:** `ki-trading-learning-loop` (Cron-Orchestration + Regel-Sync).
**Workflow-Skill:** `software-development/projekt-bauen-regeln` (v2.0.0, enthält alle obigen Fallen).

*Erstellt: 2026-08-02 · v2.7.0 · faktisch gegen live laufenden Code verifiziert.*

---

## 11. Inhalt — Was das System eigentlich macht (Fachlich)

### 11.1 Was ist Micro-Trader?
Ein **autonomes Paper-Trading-System** (Simulation, kein echtes Geld): Es kauft/verkauft
Aktien, ETFs und hochspekulative Instrumente (Krypto, Hebel, Meme) nach KI-gestützten
Entscheidungen und **lernt aus vergangenen Trades**, um künftige Entscheidungen zu verbessern.

### 11.2 Drei Anlage-Klassen
| Klasse | Depots | Logik | Risiko |
|--------|--------|-------|--------|
| **Aktien** | 20 Risikostufen (0–95, Schritt 5) | `ki_decisions.entscheide_aktien_depot` pro Stufe | moderat (RISK-Profil) |
| **ETF** | 20 Stufen (Geldmarkt→Gehebelt) | `etf_trader.py` | niedrig–hoch je Stufe |
| **Spekulation** | 48 Einzel-Depots (Watchlist) | `spec_trader.py` + `spec_watch.py` (14 Kategorien) | sehr hoch (Crypto/Hebel/Meme) |

Jedes Depot startet mit **100€** (Bargeld), handelt 1 Titel gleichzeitig, misst Rendite gegen Startwert.

### 11.3 KI-Entscheidung (pro Trade)
1. `ki_decisions.entscheide_ticker` baut Prompt mit: Marktdaten (SMA20/50, RSI, ATR),
   Positions-News (Score), **gelernte Regeln** (R1), aktuellem Regime.
2. LLM liefert: Aktion (kaufen/halten/verkaufen), Konfidenz (0–100), Begründung.
3. **Caps/Swaps greifen** (R3): Konfidenz-Cap (60), Exit-Score (Trend-Schutz),
   News-Swap (Umschichtung bei News≥75).
4. Ergebnis → `ki_log.json` (typ=decision) + `angewandte_regeln`.

### 11.4 Lern-Schleife (der Kern)
```
Trade → ki_log → Engine misst Kurs nach 4h/1d/1w
  → lerneffekt (−5…+5 je nach P&L)
  → ki_learning.analysiere_entscheidungen
  → Regeln (Anti/Swap/Multiskalen/Konzentration)
  → learned_rules.json (Source of Truth)
  → nächster KI-Prompt + skill_sync.py → Hermes-Skill
```
Die KI wird also **nicht hartcodiert**, sondern passt ihr Verhalten an Erfahrung an
(mit Decay: alte Regeln verlieren Gewicht, Ausreißer-Schutz gegen Überreaktion).

### 11.5 Engine-Bremsen (Sicherheit, ohne LLM)
- **Konzentrations-Limit:** Ticker darf max. in N Depots liegen (`max_depot_pro_ticker`)
- **Drawdown-Sperre:** Depot friert ein, wenn Wert < Peak × (1 − drawdown_sperre_prozent/100)
- **Stop-Loss / Take-Profit:** pro Position aus `risk_parameter.*`

### 11.6 News-Pipeline
`news_monitor` (RSS) → `ki_news` (LLM-Score 0–100, **VORFILTER** gegen Irrelevanz) →
nur Score ≥ `news_min_score` im Dashboard + als Entscheidungs-Input.

### 11.7 Cron-Orchestration
- **Haupt-Cron** (Hermes `c0e89575d724`, 15min, `--mode ki`): News → KI → Lernen → Skill-Sync
- **Engine-Cron** (5min, kein LLM): Scan → Bewerte → Ausführen → Bremsen
- Beide nutzen `C:\Program Files\Python312\python.exe` (kein Hermes-venv).

### 11.8 Was die KI lernt (Beispiele, live aus `learned_rules.json`)
- "NIEMALS X kaufen wenn RSI>70" (Anti-Regel)
- "Y haltet besser, Benchmark schlägt H" (Swap-Regel)
- "Bei 15min↑/1d↓ Divergenz: vorsichtig" (Multi-Timeframe)
- Diese Regeln erscheinen im Dashboard-Tab 🤖 KI-Log → "Was die KI lernt".

**Zusammenfassend:** Micro-Trader ist eine **selbstlernende Simulations-Handelsplattform**
mit 3 Anlage-Klassen, KI-Entscheidungen, gelernter Regelbasis und harten Sicherheitsbremsen —
komplett einsehbar + konfigurierbar über das Dashboard (⚙️ Einstellungen).


