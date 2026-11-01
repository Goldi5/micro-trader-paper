# Micro-Trader — Vollständige Projekt-Zusammenfassung (für KI-Übergabe)

**Zweck:** Komplett-Dokumentation für eine unabhängige KI, die dieses Projekt übernehmen/
erweitern soll. Alle Angaben gegen live laufenden Code verifiziert (2026-08-03, v2.8.4).

---

## 0. TL;DR

- **Was:** Autonomes KI-gestütztes Paper-Trading-Simulationssystem (Aktien/ETF/Spekulation)
  mit selbstlernendem Regelwerk. Kein echtes Geld, 100% Simulation.
- **Sprachen:** Python 3.12 (Backend/Engine/KI) + Vanilla-JS (Dashboard, kein Framework).
- **Runtime:** `C:\Program Files\Python312\python.exe` (NICHT Hermes-venv).
- **Dashboard:** Flask, Port **5300**, Auto-Refresh 30s, Version-Badge im Header.
- **Cron:** Hermes Job `c0e89575d724` (15min, `--mode ki`) → `micro-trader-cron.py`.
- **Settings:** 32 Felder / 7 Kategorien, Risikowarnung + Bestätigung.
- **Regeln:** 19 gelernte Regeln (über `learned_rules.lade_regeln()`), davon stabile im Skill.
- **Regel #1:** Backup vor jeder Änderung (`backup.py before/after/restore`).

---

## 1. System-Architektur

```
CRON (Hermes c0e89575d724, 15min) → micro-trader-cron.py --mode ki
  └─ micro-trader-pipeline.py --mode ki
       ├─ news_monitor.py     (RSS sammeln)
       ├─ ki_news.py          (KI-News-Bewertung + VORFILTER, Score 0-100)
       ├─ spec_trader.py      (48 Spec-Entscheidungen via ki_decisions)
       ├─ ki_decisions.py     (KI-Entscheidungen + Caps/Swaps/R1/R3)
       ├─ ki_learning.py      (Lernmodul: Regeln, Scores, Kalibrierung, 1944 LOC)
       └─ skill_sync.py       (Regeln → Hermes-Skill ki-trading-learning-loop)
Engine-Cron (5min, KEIN LLM): boersen.py, engine.py, trader.py
                              → Scan, Bewerte, Ausführen, Bremsen, Stop-Loss/TP
Dashboard.py (5300) ← liest JSON-State + ki_log.json → 9 Tabs (Vanilla-JS)
```

**Datenfluss Lernen:**
`KI-Entscheidung → ki_log.json → Engine misst Kurs (4h/1d/1w) → lerneffekt −5…+5
→ ki_learning.analysiere_entscheidungen → Regeln → learned_rules.json (Source of Truth)
→ nächster KI-Prompt + skill_sync.py → Hermes-Skill`

---

## 2. Module (Funktionen + Settings-Bindung)

| Modul | LOC | Kernfunktionen | Settings-Bindung |
|-------|-----|----------------|------------------|
| `ki_decisions.py` | 571 | `entscheide_ticker`, `entscheide_spec_batch`, `entscheide_aktien_depot`, `news_fuer_ticker`, `hole_vix` | `ki.konfidenz_cap`, `ki_temperatur`, `news_swap_min_score` |
| `ki_learning.py` | 1944 | `lerneffekt`, `lerneffekt_multiskalen`, `multi_timeframe_regel_lernen`, `news_swap_score`, `anti_muster_regeln`, `analysiere_entscheidungen`, `cross_depot_lernen`, `lade_ki_log`, `statistik`, `lade_regeln` | `lernen.anti_min_n`, `lernen.min_samples` |
| `learned_rules.py` | 503 | `lade_regeln` (Decay-Sort), `speichere_regeln`, `decay_lambda_global`, `finde_konflikte`, `lebenszyklus_status`, `regeln_mit_status`, `aktualisiere_lebenszyklus` | `lernen.decay_lambda`, `lernen.min_samples` |
| `engine.py` | ~570 | `Depot`-Klasse, `scan_markt`, `bewerte`, `signal_aktion`, `ausführen` (Konzentrations-Bremse) | `engine_bremsen.max_depot_pro_ticker`, `drawdown_sperre_prozent` |
| `trader.py` | ~560 | `berechne_indikatoren`, `Depot`-Klasse, `RISK`-Profile | `risk_parameter.moderate/aggressive_*` |
| `spec_trader.py` | ~240 | `SpecDepot`, `fetch_analyse`, `ausführen` | `depot_struktur.max_spec_depots` |
| `spec_watch.py` | ~280 | 48-Ticker-Watchlist (14 Kategorien) | — |
| `ki_news.py` | ~390 | `ist_irrelevant` (VORFILTER), `classify_headline`, `ki_bewerte_news` | — |
| `settings_loader.py` | 277 | `lade_settings`, `validiere_und_risiko`, `speichere_settings`, `LABELS` (32 Felder), Helfer `ki()/lernen()/bremse()/kapital()/depot_struktur()/risk_param()` | — |
| `dashboard.py` | 923 | Flask + 12 Routen + `boersen_chips()`, `renderSettings`, `settingsInput` | `news.news_min_score` |
| `dashboard.html` | 1944 | Vanilla-JS UI (Apple-Glass, hell) | — |
| `backup.py` | ~140 | `before/after/list/restore/rollback` | — |
| `boersen.py` | 147 | `boerse_fuer_ticker`, `BOERSEN`, `ist_offen` | — |
| `skill_sync.py` | ~200 | `lade_regeln`, `regeln_nach_gewicht`, `markdown`, `sync` (Top-15 + aktiv + OOS) | `lernen.max_regeln` |

**State-Files:** `ki_log.json` (~220KB), `learned_rules.json` (Source of Truth), `settings.json`,
`news_cache.json`, `regel_history.json` (~50KB), `system_log.json` (~80KB), `depot_XXX.json` (20×),
`etf_XXX.json` (20×), `spec_depots/*.json` (48×).

**WICHTIG — Regel-Quelle:** `learned_rules.lade_regeln()` ist die zentrale Funktion. Sie lädt
aus `learned_rules.json` (wenn vorhanden) ODER rekonstruiert aus `ki_log.json` + `ki_regeln.json`.
Das rohe `learned_rules.json` kann leer sein (0), während `lade_regeln()` 19 Regeln liefert —
das ist KORREKT (Quelle ist nicht immer das JSON-File).

---

## 3. Optik & Dashboard-Layout (Vanilla-JS, Apple-Glass, hell, v2.8.0+)

### 3.1 Design-Tokens (`:root` in dashboard.html)
| Token | Wert | Einsatz |
|-------|------|---------|
| `--bg1/--bg2` | `#F5F7FA`→`#EAF0F7` | Seitenverlauf `linear-gradient(160deg)` |
| `--card-bg` | `rgba(255,255,255,0.72)` | Panels/Cards |
| `--accent` | `#0A84FF` | Apple Blau (Primäraktion) |
| `--green/red/amber/purple` | `#30D158/#FF453A/#FF9F0A/#AF52DE` | Status/P&L |
| `--text/--text-dim` | `#1C1C1E/#6E6E73` | Text |
| `--shadow/--shadow-lg` | `0 8px 32px rgba(31,45,61,.10)` / `0 18px 50px rgba(31,45,61,.16)` | Tiefe |
| `--radius/--r-lg/--r-sm` | `14px/18px/10px` | Radien (Pills `999px`) |

- **Font:** Inter + SF Pro Fallback, `tabular-nums` für Zahlen, `font-smoothing:antialiased`
- **Glas:** `backdrop-filter: blur(24px) saturate(180%)` + Glas-Kante (border + `::after` edge2 + inset-highlight)
- **Hintergrund:** Gradient + radiale Glows (blau oben-links, grün oben-rechts, `background-attachment:fixed`)
- **Motion:** `transition: all .18s cubic-bezier(.32,.72,0,1)`, Fade-Mount mit scale, Button-Hover translateY
- **Kein Dark Mode** (hart vorgegeben, User-Wunsch)
- **Sticky Topbar:** Header mit blur(20px) + 1px Bottom-Border

### 3.2 Header
- Logo (3-Balken grün/gelb/rot) + "Micro-Trader"
- Datum/Zeit + Portfolio-Info (`20 Aktien · 20 ETF · 48 Spek`)
- **Markt-Chips** (v2.7.0): nur reale Börsen im Portfolio, Wert-Anteil % (z.B. `🔴 NYSE/NASDAQ 100%`), Crypto → `🪙 Crypto 24/7`
- Version-Badge: `🔔 v2.8.4 · Dashboard Fix` (Hover = letzte 3 Changelog)
- Notification-Bell

### 3.3 Tabs (9 Haupt-Tabs)
| Tab | Inhalt | Optik |
|-----|--------|-------|
| 📊 Übersicht | Hero + Depot-Cards pro Risikostufe, Gesamtwert/Rendite, Cron-Status | Glass-Cards |
| 📈 Aktien | 20 Risikostufen Grid, Detail-Modal mit Chart.js + News-Impact + KI-Entscheidung | Card-Grid |
| 📦 ETF | 6 Risikostufen (Geldmarkt→Gehebelt), MaxDD, Balken | Table |
| 🔥 Spekulation | 3 Subtabs (Übersicht/Positionen/Watchlist), 48 Ticker, Filter, Mini-Charts | Tabs-in-Tab |
| 📊 Analyse | Top-Ticker + Trefferquote pro Begründung | CSS-Bars |
| 📰 News | KI-bewertet (Score ≥ `news_min_score`), irrelevant rausgefiltert | Glass-Cards |
| 🤖 KI-Log | 6 Subtabs: Auswertung/Entscheidungen/News/Lerneffekte/Regeln/**Was die KI lernt** | Live-Daten |
| 📋 Log | system_log.json chronologisch | Monospace |
| ⚙️ Einstellungen | 7 C-Tabs (siehe 3.4) | Glass-Panels |

### 3.4 Settings-Tab (⚙️) — C-Tabs + kompakt + erklärt (v2.6.0+)
**7 Unter-Tabs:** 🤖 KI · 🧠 Lernen · 💰 Kapital · 📊 Depot · 🎚️ Risk · 🛡️ Bremsen · 📰 News
- **2-Spalten-Raster** pro Tab (Felder nebeneinander, 11px)
- **Natürliche Namen** (aus `settings_loader.LABELS`): "Max. Selbstvertrauen der KI" statt `konfidenz_cap`
- **Erklärung** unter jedem Feld (Layman-verständlich, 1–2 Sätze)
- **Empfohlen-Bereich** als "⚖ 40–90%"
- **Tab-Einleitung** (TAB_INTRO) pro Kategorie
- **Sicherheitsnetz:** harte MIN/MAX → Speichern blockiert; empfohlener Bereich → `confirm()`-Dialog vor Speichern
- **Reset Defaults**-Button

---

## 4. Settings-System (32 Felder, 7 Kategorien)

| Kategorie | Felder (Default) | Risikowarnung bei |
|-----------|------------------|-------------------|
| `ki` | konfidenz_cap(60), ki_temperatur(0.1), min_konfidenz_kaufen(60), exit_score_schwelle(70), news_swap_min_score(75), news_swap_aktiv(true), multi_timeframe_lernen(true) | cap<40, temp>0.3 |
| `lernen` | decay_lambda(0.01), anti_min_n(5), anti_min_widerlegt_pct(60), max_regeln(40), lern_modus(auto), min_samples(5) | decay>0.03, anti_n<3 |
| `kapital` | gesamt_budget(10000), aktien_anteil(40), etf_anteil(30), spec_anteil(30), max_gesamt_drawdown(25) | aktien>60, drawdown<15 |
| `depot_struktur` | aktien_stufen(20), aktien_schritt(5), max_spec_depots(48), etf_stufen_aktiv([6]) | stufen>20, spec>60 |
| `risk_parameter` | moderate(pos0.35/sl0.92/tp1.12), aggressive(pos0.50/sl0.85/tp1.20) | sl zu eng/weit, pos zu groß |
| `engine_bremsen` | max_depot_pro_ticker(4), drawdown_sperre_prozent(30), wochenende_handel(false) | konz>8, drawdown<15 |
| `news` | news_min_score(20), news_max_alter_std(48) | score<10 |

**API:** `GET /api/settings` (settings+limits+bools+labels), `POST /api/settings` (validiert+speichert, `bestaetigt:true` bei Warnung).
**Loader:** `settings_loader.py` (Fallback-Hardcoded bei Fehler).
**LIMITS:** harte MIN/MAX (Block) + empfohlen_min/max (Warnung) pro Feld in `settings_loader.LIMITS`.

---

## 5. Lern-System (7 Mechanismen + Prio4-Qualität)

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
**Decay (R2):** `lade_regeln()` sortiert nach `effektiv_gewicht` (gewicht × exp(-decay_lambda × tage)).
**Regeln im Prompt (R1):** `ki_decisions` baut "GELERNTE REGELN"-Block + schreibt `angewandte_regeln` ins ki_log.
**Ausreißer-Schutz (R5):** Anti-Regeln ab `anti_min_n=5` Samples, ≥60% Widerlegung.

### Prio4-Qualität (v2.8.2+, kritisch für Stabilität)
4 Qualitäts-Hebel, alle aktiv:
1. **Aktive Regeln begrenzen:** `lernen.max_regeln` (Default 40) + Skill-Sync Top-15
2. **Schwache archivieren:** `lebenszyklus_status()` + `aktualisiere_lebenszyklus()` → `archiviert:True` bei `effektiv_gewicht < 0.3`
3. **Nach Gewicht/Stabilität priorisieren:** Sortierung nach `effektiv_gewicht` (Decay angewandt)
4. **Mindestfallzahl + OOS-Bestätigung (neu v2.8.2):**
   - `lernen.min_samples` (Default 5) — jede Regel braucht ≥5 unabhängige Trades
   - `oos_confirmed` (bool) — Regel gilt erst als bestätigt, wenn nach `created_at` ≥`min_samples` unabhängige Trades sie stützen (verhindert Overfitting)
   - Neuer Status `unbestätigt` in `lebenszyklus_status()` → Regel wird NICHT in Skill exportiert, nicht im Dashboard als "gelernt" gezählt
   - **Migration (v2.8.3):** Bestehende 17 Regeln auf `oos_confirmed=True` + `support_count` gehoben, damit kein Datenverlust durch Prio4

**Skill-Sync (v2.8.1+):** `skill_sync.py` exportiert Top-15 nach effektivem Gewicht, nur aktive (nicht veraltete), Konflikt-Auflösung (höchstes Gewicht pro Muster), Hinweis-Zeile bei >15 Regeln.

---

## 6. Inhalt — Was das System fachlich macht

### 6.1 Drei Anlage-Klassen
| Klasse | Depots | Logik | Risiko |
|--------|--------|-------|--------|
| **Aktien** | 20 Risikostufen (0–95, Schritt 5) | `ki_decisions.entscheide_aktien_depot` | moderat |
| **ETF** | 20 Stufen (Geldmarkt→Gehebelt) | `etf_trader.py` | niedrig–hoch |
| **Spekulation** | 48 Einzel-Depots | `spec_trader.py` + `spec_watch.py` (14 Kategorien) | sehr hoch (Crypto/Hebel/Meme) |

Jedes Depot startet mit **100€**, handelt 1 Titel, misst Rendite gegen Startwert.

### 6.2 KI-Entscheidung (pro Trade)
1. Prompt mit Marktdaten (SMA20/50, RSI, ATR), Positions-News (Score), **gelernte Regeln** (R1), Regime
2. LLM liefert: Aktion (kaufen/halten/verkaufen), Konfidenz (0–100), Begründung
3. **Caps/Swaps (R3):** Konfidenz-Cap (60), Exit-Score, News-Swap
4. Ergebnis → `ki_log.json` + `angewandte_regeln`

### 6.3 Lern-Schleife (Kern)
```
Trade → ki_log → Engine misst Kurs (4h/1d/1w) → lerneffekt (−5…+5)
→ ki_learning.analysiere_entscheidungen → Regeln → learned_rules.json
→ nächster KI-Prompt + skill_sync.py → Hermes-Skill
```
KI wird **nicht hartcodiert**, passt Verhalten an Erfahrung an (Decay: alte Regeln verlieren Gewicht).

### 6.4 Engine-Bremsen (ohne LLM)
- **Konzentrations-Limit:** Ticker max. in N Depots (`max_depot_pro_ticker`)
- **Drawdown-Sperre:** Depot friert ein bei Wert < Peak × (1 − drawdown_sperre_prozent/100)
- **Stop-Loss / Take-Profit:** pro Position aus `risk_parameter.*`

### 6.5 News-Pipeline
`news_monitor` (RSS) → `ki_news` (LLM-Score 0–100, **VORFILTER** gegen Irrelevanz) → nur Score ≥ `news_min_score` im Dashboard + Entscheidungs-Input.

### 6.6 Cron-Orchestration
- **Haupt-Cron** (Hermes `c0e89575d724`, 15min, `--mode ki`): News → KI → Lernen → Skill-Sync
- **Engine-Cron** (5min, kein LLM): Scan → Bewerte → Ausführen → Bremsen
- Beide nutzen `C:\Program Files\Python312\python.exe` (kein Hermes-venv, `env -u PYTHONPATH` im Cron-Skript).

---

## 7. Bekannte Fallen (für künftige KI-Arbeit — kritisch!)

### 7.1 Venv-Kontamination im Cron
Symptom: `ModuleNotFoundError` im Cron. Fix: `micro-trader-cron.py` entfernt `PYTHONPATH`/`PYTHONHOME`. Manuell: `env -u PYTHONPATH -u PYTHONHOME`.

### 7.2 Dashboard-Port 5300 Zombie-Prozesse
Symptom: `curl localhost:5300/data` liefert **alte Daten**. Ursache: mehrere `dashboard.py 5300`-Prozesse. Fix: PowerShell `Get-CimInstance Win32_Process` + `taskkill /F /PID`. Verifikation: `curl /data` → `ki_lern_notizen > 0`.

### 7.3 `KI_LOG` NameError (BEHOBEN v2.8.4)
`ki_learning.lade_ki_log()` nutzte `KI_LOG` (undefiniert in ki_learning.py) → `NameError` → `dashboard.data()` lieferte 0 Regeln. Fix: `KI_LOG = os.path.join(BASE, "ki_log.json")` in ki_learning.py Zeile 22 definiert. **Dieser Bug war präexistierend**, wurde durch `env -u PYTHONPATH` getriggert (Hermes-venv hatte anderes Verhalten).

### 7.4 JSON-Corruption in `ki_log.json`
Concurrent Writes (Engine + KI) ohne Lock → `ki_decisions.schreibe_ki_log` nutzt `threading.Lock`. Bei Corruption: letzte valide Zeile behalten.

### 7.5 Regel-Quelle-Verwirrung
`learned_rules.json` kann leer (0) sein, während `learned_rules.lade_regeln()` 19 Regeln liefert. Quelle ist nicht immer das JSON-File (Rekonstruktion aus ki_log). **Niemals** rohes JSON direkt parsen — immer `lade_regeln()` nutzen.

### 7.6 Decay/Regeln-Wirkung (behoben)
`lade_regeln` sortiert nach `effektiv_gewicht` (R2). Regeln müssen im `ki_decisions`-Prompt sein (R1), sonst wirken sie nicht.

---

## 8. Regel #1: Backup vor jeder Änderung

```bash
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py before "<desc>"
# ... ändern ...
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py after  "<desc>"
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py list
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py restore <id|idx>
```
Snappt alle `*.py/*.json/*.html/*.md` (außer Logs >5MB) nach `backups/<TS>__<DESC>/`.
Aktuell: ~10 Backups vorhanden (v2.6.0 → v2.8.4), strikt befolgt.

---

## 9. Version-Log (Changelog)

`version.json` (Single Source of Truth) → Header-Badge via `/api/version`.

| Version | Datum | Codename | Kern |
|---------|-------|----------|------|
| **2.8.4** | 2026-08-03 13:55 | Dashboard Fix | ki_regeln wieder sichtbar (KI_LOG-NameError behoben) |
| 2.8.3 | 2026-08-03 13:21 | Migration Fix | Prio4-Migration: 17 Regeln gerettet (oos_confirmed + support) |
| 2.8.2 | 2026-08-03 09:30 | Prio4 Quality | min_samples (alle) + OOS-Bestätigung + Status unbestätigt |
| 2.8.1 | 2026-08-03 09:15 | Skill-Sync 15 | Top-15 + aktiv-filter + Konflikt-Auflösung + Hinweis |
| 2.8.0 | 2026-08-02 21:55 | Apple Glass | PV-Optik (Inter #0A84FF blur24 saturate180 Glas-Kante iOS-Tabs) |
| 2.7.0 | 2026-08-02 20:45 | Chips & Clarity | Markt-Chips (reale Börsen + %) · Settings-Erklärungen |
| 2.6.0 | 2026-08-02 19:30 | Compact Settings | Settings als C-Tabs + 2-Spalten-Raster |
| 2.5.0 | 2026-08-02 18:45 | Financial Settings | Finanz-Settings an trader.py + spec_trader.py gebunden |
| 2.4.0 | 2026-08-02 18:15 | Settings & Safety | Settings-Tab + Risikowarnung + Backup-System + R1–R5 |
| 2.3.0 | 2026-08-02 12:57 | Governance | R1–R5 Bestandshärtung |
| 2.2.0 | 2026-08-01 14:30 | Learning Deep | KI-Lern-Tab, News-Filter Vor+Nach |
| 2.1.0 | 2026-08-01 09:00 | Tabs & Transparency | News-Impact, Drawdown-Warnung, Cap-Badge |

**Bump-Regel:** Bei jeder abgeschlossenen Änderung `version.json` hochzählen + Changelog.

---

## 10. Quick-Start für künftige KI-Session

```bash
cd /c/Users/goldi/projects/micro-trader
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py before "meine aenderung"
# ... ändern (patch-Tool ist instabil bei großen Bloecken -> Terminal+Python-Script nutzen!) ...
# Port 5300 zuerst killen (Zombie!), dann:
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" dashboard.py 5300
env -u PYTHONPATH "/c/Program Files/Python312/python.exe" backup.py after  "meine aenderung"
```
**Verify:** Modul-Import ok · `curl /data` frisch (ki_regeln > 0) · Cron-Lauf (`tail cron_pipeline.log`).

**Tool-Hinweis:** `patch`-Tool crasht bei großen/Unicode-Blöcken ("patch content required").
Robuster: Änderungen via `"/c/Program Files/Python312/python.exe" -c "..."` (Inline-Python) oder temporäres Script + `rm`.

---

## 11. Datei-Index (Top-Module)

| Datei | LOC | Rolle |
|-------|-----|------|
| `ki_learning.py` | 1944 | Lern-Engine (Regeln, Scores, Kalibrierung, lade_regeln) |
| `ki_decisions.py` | 571 | KI-Entscheidungen + Caps/Swaps/R1/R3 |
| `learned_rules.py` | 503 | Regelbasis CRUD + Status + Konflikte + Lebenszyklus |
| `engine.py` | ~570 | Trading-Engine (Bremsen, Ausführung) |
| `trader.py` | ~560 | Basis-Trader (Indikatoren, Depot, RISK) |
| `spec_trader.py` | ~240 | Spekulations-Logik |
| `spec_watch.py` | ~280 | 48-Ticker-Watchlist (14 Kategorien) |
| `ki_news.py` | ~390 | News-Bewertung + VORFILTER |
| `settings_loader.py` | 277 | Settings-Validierung + Risiko + LABELS |
| `dashboard.py` | 923 | Flask + 12 Routen + boersen_chips |
| `dashboard.html` | 1944 | Vanilla-JS UI (Apple-Glass) |
| `backup.py` | ~140 | Backup-Helper (Regel #1) |
| `boersen.py` | 147 | Börse-Mapping (Ticker→Exchange) |
| `skill_sync.py` | ~200 | Regeln → Hermes-Skill (Top-15 + OOS) |

**Zentrale Doku:** `README.md` (Root) + Sync nach `~/AppData/Local/hermes/skills/ki-trading-learning-loop/references/`.
**Skills:** `ki-trading-learning-loop` (Cron + Regel-Sync), `software-development/projekt-bauen-regeln` (v2.0.0, enthält alle Fallen).

*Erstellt: 2026-08-03 · v2.8.4 · faktisch gegen live laufenden Code verifiziert.*
*Hinweis: learned_rules.json kann roh leer sein — immer lade_regeln() nutzen!*
