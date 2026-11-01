## [2.57.1] - 2026-08-12
### Fix: JS SyntaxError + Dashboard startet sauber (Phase 0 Vorbereitung)

**PROBLEM 1:** Browser-Konsole `Uncaught SyntaxError: Identifier 'id' has already
declared` (dashboard.html Z3304). `toggleDepotPause/depotVerkaufen/depotSchliessen/
depotLoeschen` hatten `id` als Parameter UND `const id = depotIdent(...)` im Body.

**FIX 1:** `if (!id) id = depotIdent(typ, ticker, risk);` (Parameter wins, Fallback nur
wenn nicht übergeben). node --check: OK.

**PROBLEM 2:** Dashboard lief nicht zuverlässig. Single-Instance-Guard nutzte blindes
`bind()` -> Ghost-Belegung durch TIME_WAIT nach Prozess-Kill -> "Port belegt, beende".
Flask `app.run(debug=False)` ohne `threaded=True` -> single-thread, langsamer /data
blockierte alle Requests.

**FIX 2:** Guard nutzt echten Listener-Check (`connect` statt `bind`). `app.run(threaded=True)`.

**PROBLEM 3 (aus Arbeitsauftrag):** User konnte kein zweites Depot gleichen Risikos
anlegen ("Depot existiert schon"). Bereits in v2.57.0 gelöst (eindeutige depot_uid).

**PHASE 0 DOKUMENTATION:** 5 Bestandsaufnahme-Docs erstellt (kein Code-Change):
`LIVE-NEWS-INVENTORY.md`, `LIVE-PREPARATION-ROADMAP.md`, `PAPER-SYSTEM-BASELINE.md`,
`NEWS-SOURCE-MATRIX.md`, `NEWS-LICENSE-REVIEW.md`. Basis für Live-System + News-Plattform.

---

## [2.57.0] - 2026-08-12
### Feature: Mehrere Depots pro Risiko-Stufe (eindeutige depot_uid)

**PROBLEM:** User legte Aktien-Depot mit Risk 100 an -> "Depot existiert schon:
aktien:100". `risk` war als Depot-ID/Dateiname hartcodiert -> zwei Depots
gleichen Risikos kollidierten. Dashboard zeigte nur 20 (RISK_STUFEN).

**LOESUNG (Option A):** Eindeutige `depot_uid` durchgängig.
- `depot_erstellen`: Dateiname `depot_{risk:03d}_{seq:02d}_paper.json`,
  `depot_id = aktien:{risk}` (Legacy, seq=0) oder `aktien:{risk}:{seq}`.
- Jede Depot-Datei bekommt Feld `depot_id` + `seq`.
- `_depot_pfad_aus_id` parst `aktien:100:1` -> `depot_100_01_paper.json`.
- `/data` nutzt `depot_raw_list` (Liste, nicht Dict nach risk) -> mehrere
  Depots pro risk sichtbar. Jedes Depot-Dict hat `"id"`.
- `/depot_json` akzeptiert `id=`-Parameter (Fallback auf `risk=`).
- Frontend: `depotIdent(typ,ticker,risk,id)`, `showDepot` ruft
  `/depot_json?id=...`, Aktions-Buttons (Pause/Verkaufen/Schließen/Löschen)
  übergeben `dep.id`.
- `batch_trader` erfasst neue Dateien automatisch (Glob-Scan).

**VERIFIKATION:** 2 Depots Risk 100 (aktien:100:1, aktien:100:2) + Legacy
aktien:100 + Risk 55 (aktien:55) erscheinen ALLE in /data. batch_trader
scannt alle. Frontend-Buttons verdrahtet. Keine Kollision mehr.

---

## [2.56.1] - 2026-08-12
### Fix: Neue Depots mit Risk > 95 erscheinen nicht in Aktien-Liste

**BUG:** User legte Aktien-Depot mit Risk 100 an (Name "Neue Aktien Test").
Erschien NICHT in der Aktien-Uebersicht.

**ROOT-CAUSE:**  /data Route iterierte 
(RISK_STUFEN = range(0,100,5) = max 95). Depots mit Risk 100 (oder andere
nicht-Stufen-Werte) wurden vom Rendering uebersprungen, obwohl die Datei
existierte und  sie korrekt erfasste.

**FIX:**  -> 
(alle geladenen Depots, nicht nur RISK_STUFEN).

**VERIFIKATION:** depot_100_paper.json (risk 100, name "Neue Aktien Test")
wird jetzt in /data erfasst. batch_trader (Task 4 Scan) handelt es ohnehin.

---

# Changelog

## [2.56.0] - 2026-08-12
### Einzel-Depots neu eröffnen (Budget + Risiko)

**Feature:** User kann im Dashboard ein NEUES Aktien-/ETF-/Spec-Depot eröffnen
(analog zu Schließen/Löschen), mit eigener Budget-Höhe ($) + eigenem Risiko (0-100).
Erscheint in derselben Liste wie die bestehenden Depots.

**Änderungen:**
- `depot_erstellen(kat, risk, budget, name)` Helfer in `dashboard.py` (schreibt neue Depot-JSON)
- API-Route `POST /api/depot_neu` (kategorie, risk, budget, name) — Auth-Pflicht
- Dashboard-UI: Button "+ Neues Depot" (fixed bottom-right) + Modal (Kategorie-Dropdown,
  Risiko-Slider 0-100, Budget $, Name) — Glassmorphism #2563eb
- `batch_trader.py`: Depot-Scan auf ALLE `depot_*.json`/`etf_*.json`/`spec_depots/*.json`
  umgestellt (statt nur `RISK_STUFEN`) → neu eröffnete Depots werden AUTOMATISCH gehandelt
- `laden_aus_datei()` Helfer (lädt Depot aus existiender Datei)

**Verifikation:** Route existiert (401 ohne Login), `depot_erstellen()` schreibt Datei,
Scan erfasst `depot_042_paper.json` (Risk 42) korrekt.

---

# Changelog

## [2.55.0] - 2026-08-11
### Dashboard-Stabilität + KI-Ketten-Beobachtung (P11-User-Feedback)

**Dashboard-Verbesserungen (User-Feedback "alle 5 bitte"):**
- **Broker-Tab**: echte Inhalte (Paper-Cash, Positionen-Anzahl, Orders, Sync-Status) statt Minimal-Anzeige
- **Risk-Appetite-Slider**: steuert jetzt echte KI-Strategie (konservativ/ausgewogen/aggressiv) — Profil als Prompt-Text + Erklärzeile; `ki_decisions` nutzt `risk_appetite_profil()` im Prompt
- **Portfolio-Filter-Bug**: harter Slice auf 6 Karten entfernt → alle Portfolios werden geladen (Pagination bei Bedarf)
- **Analyse-Tab-Umbau**: Untertabs `📊 Analyse` / `🧠 KI-Auswertung` (128+ decisions) / `🧠` / `📚 Lerneffekte` (pending_rules)
- **News-Tab**: aus `ki_log` ausgelagert, Tabelle (Zeit/Ticker/Prio/Event/Richtung/KI-Bewertung), filterbar

**Stabilitäts-Fixes:**
- `security_users.json` Korruption + `db_karten` 500 (atomic save + optional lock)
- Single-Instance-Guard Dashboard (Port 5300) — beendet Doppel-Starts
- Login-Page aufgehübscht (Segoe UI Variable, Slate) + Logout → Landingpage

**KI-Ketten-Beobachtung (Börse offen, mehrfache Prüfung A–I):**
1. **pending_rules → learned_rules Übernahme**: Regeln mit `violation_count >= 5` werden validiert übernommen (waren ewig "offen"/OOS)
2. **News-Ticker-Map Firmenname-Fallback**: 35 statische Firmen + Depot-Namen → News-Zuordnung 57% → 70%
3. **KI-Parse-Fehler sichtbar**: `schreibe_ki_log(typ="error")` statt stillem `except: pass`
4. **ki_log.json Vollverlust behoben**: `schreibe_ki_log` war Read-Modify-Write-Race → bei Concurrent-Writes `JSONDecodeError` → `log=[]` → komplett geleert. Jetzt: atomarer Write (temp+os.replace) + Optimistic-Retry, kein Leeren bei Parse-Fehler

**Fix (Nachbeobachtung): Konfidenz-Cap Regeln explodierten** — `OOS offen` Regeln wuchsen unendlich (Dedup-Schlüssel enthielt Live-Werte quote/n). Stabiler Key `[Meta] Konfidenz-Cap {cap}` → 48 → 17 Regeln (Dedup hält).

**Verifiziert (ad-hoc, keine grüne Test-Suite):** 17/17 + 12/12 + 6/6 + 11/11 + 5/5 PASS (jeweils Live-Checks gegen laufendes Dashboard/Module).

## [2.54.0] - 2026-08-11
### Roadmap Live-Freigabe: Depotsteuerung + News-Pipeline + MarketSnapshot + Broker
**P4/P5:** Depot-Steuerung pro Depot (Aktien/ETF/Spec):
- `/api/depot_pause` (Toggle pro Depot), `/api/depot_verkaufen` (alle Positionen),
  `/api/depot_schliessen` (CLOSED), `/api/depot_loeschen` (nur in Kette:
  verkauft + CLOSED → Backup-Verschiebung, kein hartes Löschen)
- 4 Buttons in jeder Depot-Detailansicht (⏸ 💸 🔒 🗑)

**Roadmap Punkt 2+3 (News-Pipeline):**
- `news_evaluator.py`: alter OPENCODE_GO/Zen-Direktaufruf → `ki_provider.call_ki`
  (reparierter Pool: openrouter Primary, nous-hy3/step, zen ling)
- Ticker-Map aus WATCHLIST/Depots, Dedup via hash(title+url), dedup_id
- News-Prompt: urgency P0-P3 + event_type + direction (Handoff-V3-Schema)

**Roadmap Punkt 5 (MarketSnapshot):**
- `market_snapshot.py`: Snapshot-ID (md5), Datenalter-Gate (3 Tage wie
  paper_eligibility), KI-Prompt-Injektion "MARKTDATEN-SNAPSHOT <id> [frisch|VERALTET]"

**Roadmap Punkt 8 (Broker):**
- Broker-Tab im Dashboard (`/api/broker_status`, PaperBrokerAdapter, keine Keys)
- Broker-Check: Alpaca Europe verfügbar (Xetra DE, CNMV/MiFID II), B2B-fokussiert,
  Live-Zugang für Privatkunden separat prüfen
- Security-Fix: `_save_users` Merge-Schutz (Passwort-Loop Root-Cause)

## [2.51.0] - 2026-08-10
### Fixed (KI-Provider-Pool repariert — Trading wieder fundiert)
**Problem:** KI-Entscheidungen im Trader fielen auf Sicherheits-Fallback `halten`
(10/20 Spec ohne fundierte KI). Ursache: alle Free-Tier-Provider im `ki_provider`-
Pool tot/kaputt.

**Root-Cause + Fix (je Provider):**
| Provider | Modell (vorher) | Status | Modell (nachher) | Fix |
|---|---|---|---|---|
| OpenRouter | `nemotron-3-ultra-550b-a55b:free` | ❌ 78s Timeout | `nvidia/nemotron-3-nano-30b-a3b:free` | ~1–3s, **Primary** |
| nous-hy3 | `tencent/hy3:free` | ❌ leeres content | gleich (max_tokens-Lift) | `_ki_call` hebt `max_tokens` für hy3/step auf **≥2048** (Reasoning-Modell lieferte bei <2048 nur `finish_reason=length`) |
| nous-step | `stepfun/step-3.7-flash:free` | ✅ (vorher 400 durch falsches Test-Format) | gleich | max_tokens-Lift wie hy3 |
| zen (OpenCode) | `deepseek-v4-flash-free` | ❌ 429 `FreeUsageLimitError` (Quota leer) | `ling-3.0-flash-free` | funktioniert ~7s als Puffer |
| zen (laguna-s) | `laguna-s-2.1:free` | ❌ 401 `ModelError` | — | **nicht in diesem Zen-Account autorisiert** (trotz öffentlicher Modellliste) |

**Weitere Fixes:**
- `ki_cooldown.json` (Circuit-Breaker) sperrte alle Provider dauerhaft → **gelöscht**, Provider wieder testbar.
- OpenRouter-Header (`HTTP-Referer`/`X-Title`) in `get_client` ergänzt (sonst leere Antworten).
- Provider-Reihenfolge Cron-Pool: **openrouter → nous-hy3 → nous-step → zen(ling) → zen-nemotron**.

**Verifikation (ad-hoc, 8/8 PASS):** openrouter 3.8s OK · nous-step 4.0s OK ·
nous-hy3 8.6s OK · zen(ling) 1.3s OK · hy3/step-max_tokens≥2048-Lift aktiv ·
OR-Header gesetzt. Live-`call_ki` liefert in 2.4s fundierte Antwort.

**Ergebnis:** Letzter KI-Run 21:16, 20/20 Spec mit Aktion, nur 4 Fallback (vorher 10).
Commits: `6d1c5aa` + `7a9bcc1`.

## [2.50.0] - 2026-08-10
### Added (Platform Expansion §19-Punkt 12: Order-Intent + Risk-Integration, §13)
- **`validate_order_intent` erweitert auf 18-Punkte-Checkliste** (Auftrag §13):
  Modus/PAPER_ONLY, Menge/Ticker, Markt, Max-Positionen, Risiko, Regeln,
  Vier-Augen, **Trading-Pause**, **Tenant-Mismatch**, **Benutzer-darf-handeln**,
  **Portfolio-aktiv**, **Broker-Connection-Tenant**, **Broker-Umgebung≠Modus**,
  **Daten-aktuell (Preis>0)**, **Drawdown-Limit**, **Doppelte-Order**
- **Bugfix `create_order_intent`**: `price`-Parameter wurde nicht ins Intent-Dict
  geschrieben (Killswitch für Preis-Check) → jetzt `price`→`limit_price`+`price`
- **Hilfsfunktionen**: `_trading_paused`, `user_can_trade`, `_portfolio_active`,
  `_broker_connection_for_tenant`, `_duplicate_order` (alle tenant-scoped)
- **Tests**: 7 P12-Tests (18-Check, price-Bug, LIVE/Tenant/Menge/Preis-Block) → **306 OK / 0 FAIL**

### Security
- Order-Intent ist jetzt hart gegen Tenant-Mismatch, ungültige Preise, doppelte Orders
- `PAPER_ONLY` bleibt unumgänglich (LIVE blockiert)

## [2.47.0] - 2026-08-10
### Added (Platform Expansion §19-Punkt 11: Paper-/Simulator-Broker, §10)
- **`SandboxBrokerAdapter`** (security.py): simulierter Broker (Market-Fill, environment=SANDBOX), erbt von `BrokerProvider`
- **`get_broker_adapter(environment)`** Factory: liefert Paper/Sandbox-Adapter je Umgebung
- Sandbox-Orders laufen durch `validate_order_intent` + `paper_order_insert`/`paper_position_apply` (tenant-scoped, PAPER_ONLY)
- **Tests**: 8 P11-Tests (Interface, Factory, Sandbox-Order, PAPER_ONLY, Health) → **299 OK / 0 FAIL**

### Security
- Kein Live-Adapter, keine Echtgeld-Pfade (PAPER_ONLY hart)

## [2.46.0] - 2026-08-10
### Added (Platform Expansion §19-Punkt 10: Datenprovider-Abstraktion, §12)
- **`market_data_provider.py`** (neu): `MarketDataProvider`-Interface + `MarketSnapshot`-Dataclass (alle §12-Felder)
- **4 Concrete Provider**: YahooMarketData, FinnhubMarketData, TwelveDataMarketData, AlphaVantageMarketData (alle wrappen `marktdaten.py`-Backend)
- **Fallback-Kette**: `get_quote_with_fallback` (Reihenfolge yahoo→finnhub→twelvedata→alphavantage)
- **Kein stiller 0-Kauf**: ungültige Ticker → leeres `MarketSnapshot(quality="unknown")`
- **Health-Check**: `health_all()` für alle Provider
- **Tests**: 9 P10-Tests (Interface, Snapshot-Felder, Fallback, ungültiger Ticker, Health, Abstraktion) → **291 OK / 0 FAIL**
- **Doku**: MARKET-DATA-ABSTRACTION.md (§20)

### Note
- Trading-Core (`engine.py`/`ki_decisions.py`/`dashboard.py`) importiert noch direkt `yfinance` (Legacy). Abstraktion ist vorhanden + wird für neue Pfade genutzt; vollständiger Refactor der Legacy-Calls ist eigener Risiko-Schritt (nicht in dieser Phase).

## [2.45.0] - 2026-08-10
### Added (Platform Expansion §19-Punkt 9: Secret-/Connection-Manager)
- **Provider-Connection Status-Workflow** (db.py): `PROVIDER_CONN_STATES` (UNCONFIGURED/CONFIGURED/TESTING/HEALTHY/DEGRADED/FAILED/DISABLED/EXPIRED) + `PROVIDER_CONN_TRANSITIONS` (Guard gegen illegale Sprünge) + Legacy-Compat (`aktiv`/`fehler` gemapped)
- **Tenant-scoped Connection-Operationen** (db.py): `provider_connection_get`, `set_status`, `disable`, `enable`, `delete` (alle tenant_id-geprüft, Cross-Tenant geblockt)
- **Secret-Rotation** (db.py): `secret_rotate` (neuert Wert, Audit-fähig), `secret_last4` (nur letzte 4 Zeichen, niemals Klartext)
- **API-Routen** (dashboard.py): `/api/providers/disable|enable|delete|status/<id>`, `/api/secrets/rotate` (alle TENANT_ADMIN, in ROUTE_ACCESS registriert)
- **Audit**: alle Provider/Secret-Operationen via `sec.audit_log` (kein Klartext/Secret im Log)
- **Tests**: 9 neue P9-Tests (Status-Transition, Illegal-Sprung-Block, Cross-Tenant-Block, Rotation, Redaction) → **282 OK / 0 FAIL**
- **Doku**: PROVIDER-MANAGEMENT.md, SECRET-CONNECTION-MANAGEMENT.md (§20)

### Security
- Kein Klartext-Secret in API-Responses (nur `last4`), keine Secrets in Logs/Audit
- Provider-Operationen strikt tenant-scoped (Cross-Tenant-Angriff blockiert)

## [2.44.9] - 2026-08-09
### Added (UI-Redesign Phase 15: Feinschliff pro Bereich)
- **Badge-Konsistenz** (Portfolios-Übersicht): Modus/Status-Badges auf einheitliches `.badge-modus` (grau/Slate) + `.badge-modus-active` (Slate-Blau) umgestellt — kein rotes `badge-meme` mehr für LIVE/Gesperrt
- **Glass-Relikte entfernt** in KI-/News-/Settings-/System-Bereichen: alle `rgba(255,255,255,0.0x)`-Hintergründe/Borders → `var(--surface-muted)` / `var(--border)`; alle `rgba(139,92,246,0.x)`-Purple (außer bewusst KI-Lila bei Lernmodul/swap) → `var(--primary-soft)`
- **Farben vereinheitlicht**: Hardcoded `#10b981/#f59e0b/#ef4444` in KI-Stats → `var(--success)/var(--warning)/var(--danger)`; `var(--text-dim)` → `var(--text-secondary)` (Alias)
- **Verifikation**: `node --check` clean, 0 Glass-RGBA verbleibend, Live-Login OK

## [2.44.8] - 2026-08-09
### Verified (UI-Redesign Phase 13: Regression + visuelle Prüfung)
- **Regression**: Alle 8 Bereiche (Übersicht, Portfolios, Märkte, Analyse, Aktivität, KI, System, Einstellungen) + Portfolios-„Alle" rendern fehlerfrei, keine JS-Console-Fehler
- **Drawer**: öffnet bei Karten-Klick, schließt bei Escape, max. 6 Karten in Portfolios-Übersicht
- **Visuell verifiziert** (Browser-Screenshot): dunkle 56px-Topbar, weiße opake Flächen, Slate-Blau (#2563eb) als Akzent, ruhige Hierarchie, **kein** Glassmorphismus
- **/data** liefert strukturierte Depots (depots=20, etf=20, spec=49)

## [2.44.7] - 2026-08-09
### Added (UI-Redesign Phase 12: Accessibility)
- **Skip-Link** („Zum Hauptinhalt springen", bei Fokus sichtbar)
- **`role="main"`** + `id="main-content"` + `tabindex="-1"` auf Hauptinhalt
- **Karten als `role="button" tabindex="0"`** mit Keyboard-Handler (Enter/Space → Drawer), alle drei Render-Pfade (Portfolios, Aktien/ETF, ETF-Glass)
- **Focus-visible** Outline (bereits vorhanden, bestätigt)
- Keine Logik-Änderung, nur ARIA/Tastatur-Zugang

## [2.44.6] - 2026-08-09
### Added (UI-Redesign Phase 11: Responsive)
- **Portfolios-Übersicht responsiv**: Summary-Stats und Filterleiste umbrechen auf Mobile (Selects/Input → 100% Breite bei ≤768px)
- **Karten-Grid** auf Mobile 1-spaltig (≤480px)
- Bestehende Media-Queries (1200/1024/768/480px) bleiben erhalten
- Keine Logik-Änderung, nur CSS

## [2.44.5] - 2026-08-09
### Reviewed (UI-Redesign Phase 10: Login/MFA)
- **Keine Änderung an `dashboard.html`** — das Login-/MFA-Formular liegt in `dashboard.py` (Flask-Route `login()`), Security-kritisch (Session-Cookies, Rate-Limit). Gemäß harter Vorgabe §2.1 (keine Security-/Tenant-Logik) bewusst **nicht** angefasst.
- Das Formular ist ohnehin minimal (kein Glassmorphismus, keine Dashboard-CSS-Referenz) → keine Design-Inkonsistenz vorhanden.

## [2.44.4] - 2026-08-09
### Added (UI-Redesign Phase 9: Einstellungen + Admin)
- **Settings-Box** & **Analyse2-Wrapper**: `glass` → `surface`
- **Analyse-Input/Button**: Glass-Purple/Transparent → `var(--surface)` + `var(--border)` + `var(--primary)`
- **Reset-Button** (Settings): `rgba(255,255,255,0.2)` → `var(--border)`
- Keine Logik-Änderung, nur Darstellung (Aliased Tokens `--accent`/`--text-dim` bereits auf Designsystem gemappt)

## [2.44.3] - 2026-08-09
### Added (UI-Redesign Phase 8: KI/News/Aktivität)
- **KI-Subtabs** auf Designsystem umgestellt (opake `.ki-subtab` mit Primary-Aktiv-Zustand statt Glassmorphismus)
- **News-/Log-/Lern-Boxen**: `glass` → `surface` (konsistente opake Flächen)
- **KI-Markt-Badges** & Analyse-Sticky-TH: Glass-Purple `rgba(139,92,246,...)` → `var(--primary-soft)` / `var(--surface-muted)`
- Keine Logik-Änderung, nur Darstellung

## [2.44.2] - 2026-08-09
### Added (UI-Redesign Phase 7: Tabellen/Datenansichten)
- **`.table-scroll`**: Tabellen scrollen horizontal auf schmalen Viewports (statt Zeilenumbruch)
- **`.num-col`**: Zahlen-Spalten rechtsbündig + `tabular-nums` (konsistente Ausrichtung bei Kursen/Prozenten)
- **Sortier-Indikator**: `th.sortable` mit `.sort-ico` (▲/▼) bei aktiver Spalte in der Spekulations-Watchlist
- Keine Logik-Änderung, nur Darstellung/Robustheit

## [2.44.1] - 2026-08-09
### Added (UI-Redesign Phase 6: Portfolios)
- **Portfolios-Hauptbereich** mit Sub-Nav (Alle / Aktien / ETF / Spekulation)
- **Portfolios-Übersicht („Alle")**: ruhige Karten-Übersicht, **max. 6 Karten**, je Karten nur Name/Kategorie/Wert/Rendite/Modus/Risiko/Positionen/Status (Reduktion der Datendichte gem. §2.1)
- **Filterleiste**: Kategorie, Modus (Shadow/Paper/Live), Risiko (Niedrig/Mittel/Hoch), Status (Aktiv/Frei/Gesperrt), Suche (Ticker), Sortierung (Wert/Rendite/Risiko)
- **Klick auf Karte** → öffnet bestehenden Detail-**Drawer** (Phase 5), keine neue 3-Spalten-Ansicht
- **Summary-Statistik** oben: Gesamtwert, Ø-Rendite, Anzahl Portfolios, Aktiv, Gesperrt, Modus
- Keine Änderung an Trading-/KI-/Risk-/Security-/Tenant-Logik (nur Frontend-Rendering + Filter)

## [2.44.0] - 2026-08-09
### Added (UI-Redesign Phasen 2–5: Calm Trading Foundation)
- **PHASE 2 (Designsystem):** Neues Token-Set „Calm Trading Command Center" — opake weiße Flächen (`--surface:#ffffff`), Hintergrund `#f7f9fc`, Slate-Blau `#2563eb`; Glassmorphismus entfernt. Alte Variablennamen als Alias-Block erhalten (498 Inline-Styles funktionsfähig).
- **PHASE 3 (Header/Navigation):** Dunkle 56px-Topbar (Logo, 8 Bereiche: Übersicht/Portfolios/Märkte/Analyse/Aktivität/KI/System/Einstellungen, Suche, User-Menü). Sub-Navigation via `AREA_MAP`/`AREA_SUBS` (Portfolios: Aktien/ETF/Spekulation; Analyse: Analyse/Analyse DB).
- **PHASE 4 (Startseite):** Hero mit Gesamtwert (44px), 4 KPI-Karten (Aktien/ETF/Spekulation/System), 2-spaltiges Layout (Portfolio-Verlauf + KI-Konfidenz links, Aktivität rechts), Risiko- + KI-Status unten.
- **PHASE 5 (Drawer):** Slide-in Detail-Drawer (480px, Overlay, Escape-Close, Body-Scroll-Lock); `showDepot()` auf Drawer umgeleitet; ARIA-Attribute (`role=dialog`, `aria-modal`, `aria-hidden`).
- **Sicherheit:** Keine Änderung an Trading-/KI-/Risk-/Shadow-Paper-Live-/Provider-Logik, Security-Gates, Rollen oder Tenant-Isolation. `/data` ohne Auth liefert weiterhin JSON 401 (kein HTML-Redirect).
- **Verifikation:** Alle 8 Bereiche + Sub-Nav getestet; Drawer öffnet/schließt via Escape; Body-Lock korrekt; Login/Session intakt.

## [2.43.0] - 2026-08-09
### Added (PHASE 5: Shadow→Paper-Freigabe — §9 / §19-Punkt 7)
- **8 Voraussetzungen in `paper_eligibility`:** Shadow-Mindestanzahl (≥20 KI-Entscheidungen), Audit-Trail vollständig, Regelstand identifizierbar, keine kritischen Fehler (7 Tage), keine ungelösten Block-Regeln, Providerdaten stabil (markt_daten < 3 Tage), Portfolio tenant-scoped, Shadow/Paper getrennt.
- **Getrennte Portfolios:** PAPER nutzt `depot_<risk>_paper.json` / `etf_<risk>_paper.json` / `spec_depots_paper/` — Shadow-Positionen werden nie übernommen, jedes Paper-Depot startet leer.
- **mode-Feld** in allen Depot-Speichern (Default `shadow`, rückwärtskompatibel).
- **`_tenant_scoped_depot_files(tid, mode)`** filtert zusätzlich nach Portfolio-Modus.
- **/data-Cache tenant- UND mode-keyed** (`_cache_mode`) — Moduswechsel liefert nie fremde Daten.
- **`portfolio_verlauf(tage, mode)`** aggregiert nur den aktiven Portfolio-Satz — keine gemeinsame Shadow/Paper-Bewertung (§9-Verbot).
- **Trader-Mode-Gates:** batch/etf/spec `main()` nutzen den Portfolio-Satz des aktiven Modus.
- **Doku:** `SHADOW-PAPER-APPROVAL.md` (Ergebnisdatei §20).
- **Tests:** Sektion 7r (+14) → **273 OK, 0 FAIL**.

## [2.42.0] - 2026-08-09
### Added (PHASE 4: Shadow/Paper/Live-Zustandsmaschine vervollständigt — §8 / §14)
- **Batch-Trader Mode-Gate:** `main()` bricht bei `PAUSED`/`SUSPENDED`/`REVOKED`/`LIVE_*` sofort ab (Log + Return) — vorher hätte der Cron auch in gesperrten Zuständen weitergetradet.
- **Vier-Augen + MFA bei LIVE-Übergängen:** `LIVE_APPROVED`/`LIVE_ACTIVE` erfordern `approved_by` (anderer User als Antragsteller, kein Selbst-Genehmigen §14) + `mfa_confirmed=1`; sonst `ValueError` + kein Moduswechsel.
- **`allowed_transitions`:** GET `/api/trading_mode` liefert die erlaubten Folgezustände aus der State-Machine (Frontend-Basis).
- **TEMP-DEBUG entfernt:** `_budget_debug.txt`-Block (Risk 80/90) aus `batch_trader.py` gelöscht (Phase-0-Befund).
- **Doku:** `TRADING-MODE-STATE-MACHINE.md` (Ergebnisdatei §20).
- **Tests:** Sektion 7q (+17) → **259 OK, 0 FAIL**.

## [2.41.0] - 2026-08-09
### Added (PHASE 3: Tenant-Isolation verifizieren und absichern — §2.3 / §17 / §18)
- **`/data`-Cache tenant-keyed (`_cache_tid`):** Cache-Hit nur noch bei identischer `tenant_id` — **Cross-Tenant-Leak geschlossen** (Tenant B bekam zuvor die gecachten Portfolio-Daten von Tenant A im 60s-Fenster).
- **Tenant-Routen auf effektive Rolle:** `/api/tenants`, `/api/tenants/create`, `/api/tenants/<tid>/members` (GET+POST) nutzen `require_tenant_role("admin")` statt `require_role("admin")`; ROUTE_ACCESS auf `TENANT_ADMIN` umgestellt (before_request setzt den Tenant-Kontext).
- **`tid`-Guard:** non-superadmin darf ausschließlich seinen eigenen Tenant lesen/verwalten (403 bei fremder `tid` aus der URL) — Tenant-ID aus dem Request wird nicht vertraut (§18).
- **Tenant-Liste isoliert:** non-superadmin sieht nur seinen eigenen Tenant; Tenant anlegen nur noch durch superadmin (403 sonst).
- **Depot-Dateien tenant-markiert:** `engine.py`/`spec_trader.py`/`etf_trader.py`/`trader.py`/`paper_trader.py` schreiben `tenant_id` (Default 1) — `_tenant_scoped_depot_files` ordnet Depots korrekt zu, kein Rückfall auf Tenant 1 bei Tenant-2-Depots.
- **Doku:** `TENANT-ISOLATION-VERIFICATION.md` (Ergebnisdatei §20).
- **Tests:** Sektion 7p (+11) → **242 OK, 0 FAIL**.

## [2.40.0] - 2026-08-09
### Added (PHASE 2: Rollen & Berechtigungen ausbauen — Auftrag §7)
- **Feine Permission-Kataloge:** `FINE_PERMISSIONS` (41 Permissions aus dem §7-Katalog: `profile.*`, `sessions.*`, `dashboard.read`, `portfolio.*`, `reports.read`, `analysis.read`, `strategy.*`, `rules.*`, `trading.pause/resume`, `paper.trade`, `live.request/review/approve/revoke`, `provider.*`, `broker.*`, `order.intent.*`, `users.*`, `roles.manage`, `audit.read`, `settings.*`, `backup.restore`) + `ROLE_FINE_PERMISSIONS` je Rolle — **deny-by-default** (nur explizit Erlaubtes zählt).
- **Alias-Auflösung (`PERMISSION_ALIASES`):** grobe Katalog-Namen (`users`, `rules`, `audit`, `settings`, `backups`, `dashboard`, …) implizieren ihre feinen Permissions — bestehende Checks bleiben kompatibel.
- **Prüfebene vereinheitlicht:** `role_has_permission` / `has_permission` / `has_permission_in` / `effective_permissions` prüfen jetzt fein + grob + Alias; superadmin hat weiterhin alles.
- **Selbst-Privilegierung blockiert (§7-Vorgabe):** `set_role` verweigert jeden Promote auf sich selbst (Rolle unverändert, Audit `role_change_denied`); Selbst-Downgrade bleibt erlaubt.
- **Superadmin-Schutz:** superadmin-Rolle kann nur durch einen superadmin vergeben oder entzogen werden (auch Downgrade).
- **API:** `POST /api/users/<name>/role` → 403 bei verweigertem Wechsel; `GET /api/roles` verlangt `roles.manage` (MFA-Pflicht-Route) und liefert feine Permissions je Rolle.
- **Doku:** `ROLE-PERMISSION-MATRIX.md` (Ergebnisdatei §20) — Matrix, Alias-Tabelle, Vorgaben-Umsetzung, Testabdeckung.
- **Tests:** Sektion 7o (+48) → **231 OK, 0 FAIL**.

## [2.39.0] - 2026-08-09
### Added (PHASE 1: Benutzerverwaltung professionalisiert — Auftrag §6)
- **Benutzer-Status-Lebenszyklus:** `INVITED / ACTIVE / MFA_REQUIRED / RESTRICTED / SUSPENDED / DISABLED / DELETED`. Migration alter `active`-bool-Daten in `_load_users()` (admin ohne MFA → `MFA_REQUIRED`, inaktiv → `DISABLED`).
- **Neue User-Felder:** `created_by`, `updated_at`, `last_login_at`, `last_failed_login_at`, `mfa_verified_at`, `disabled_by`, `disabled_at`, `recovery_codes`.
- **Sessions-GC:** `_load_users()` entfernt abgelaufene Sessions (Idle > 30 min, Absolut > 8 h) — behebt unbegrenztes Session-Wachstum (vorher 422 Sessions für admin).
- **Passwortänderung widerruft ALLE Sessions** (`change_password` → `sessions={}`, Akzeptanzkriterium §6).
- **MFA-Änderung invalidiert Sessions + erzeugt Audit:** `enable_mfa` (mfa_verified_at, Status → ACTIVE), `disable_mfa` (Sessions geleert, Status → MFA_REQUIRED für Pflicht-Rollen), `verify_recovery_code` (Audit `mfa_recovery_used`).
- **MFA-Pflicht für Admin/Superadmin:** `mfa_recently_verified` → False ohne MFA; `require_recent_mfa` leitet auf `/setup_mfa` (Einrichtung) bzw. `/mfa` (Reauth) um — **kein Login-Lockout**. Angewendet auf: `/admin/users`, `/admin/security`, `/api/users`, `/api/users/create`, `/api/users/<name>/role|deactivate|reset-pw|revoke`.
- **Recovery-Codes:** 8 einmalige Codes (`RECOVERY_CODE_COUNT=8`, Basis32 ohne 0/O/1/I) bei MFA-Aktivierung; `verify_recovery_code()` verbraucht einen.
- **Redaction (Sicherheitsfix):** `get_user()`/`list_users()` liefern nie mehr `password_hash`, `mfa_secret`, `recovery_codes` — neue `_user_view()`-Schicht; `/api/users` nutzt `mfa_enabled`/`status`/`sessions_active` statt Secrets.
- **API:** `create_user` mit `email`/`display_name`/`created_by`; Deaktivierung über `sec.deactivate_user` (Status+disabled_by/at+Audit); Reaktivierung berechnet Status neu (MFA-Pflicht beachtet).
- **Tests:** Sektion 7n (+18) → **183 OK, 0 FAIL**.

## [2.38.1] - 2026-08-09
### Fixed (Bugfix-Release: 3 vom User gemeldete Bugs)
- **FIX 1 — Freigabe wirkt jetzt im Order-Pfad:** `validate_order_intent` prüft die Portfolio-Freigabe über `enforce_approval_trade()` (neu). Semantik: **unregulierte Ziele** (kein Freigabeeintrag) laufen weiter — der Paper-Betrieb wird nicht lahmgelegt; **explizit gesperrte / in Prüfung** stehende Portfolios blocken die Order hart. `enforce_approval()` selbst bleibt deny-by-default (Sicherheits-API, §23).
- **FIX 2 — BLOCK-Regel-Matching-Bug (Z291):** `enforce_rules` unterscheidet jetzt Ticker-spezifische Sperren von generischen: `BLOCK:GME …` blockt **nur** GME (Ticker-Symbol = 1–5 Großbuchstaben direkt nach `BLOCK:`), `BLOCK:manuell gesperrt` (ohne Symbol) blockt weiterhin **alle** Ticker. Regressionstests: passender Ticker geblockt, fremder Ticker frei, Anti-/Tenant-Regeln unverändert.
- **FIX 3 — KI-Regeln wirken im Enforcement:** `db.effective_rules` reicht `freigabe_status`, `shadow`, `typ` aus `learned_rules.json` durch (vorher nur id/muster/regel/status/source). `enforce_rules` aktiviert freigegebene **globale** KI-Regeln (`source=="global"` + `freigabe_status=="freigegeben"` + nicht shadow) zusätzlich zu `status=="aktiv"` — Tenant-Regeln schalten weiterhin ausschließlich über `status` (pausiert/unbestätigt blocken nicht).
- **FIX 3b — KI-Muster mit Ticker-Bezug:** Muster `[MTF] … (RIVN)`, `[Swap] … (SPY)`, `[Konzentration] AMC …` blocken **gezielt** den genannten Ticker, andere Ticker bleiben frei. `meta_conf_cap`-Regeln blocken nicht hart (sie steuern den KI-Prompt über ki_decisions, kein Order-Block).
- **Tests:** Sektion 7m (+14) → **165 OK, 0 FAIL**.

## [2.38.0] - 2026-08-09
### Added (PHASE 14: Freigabe-Workflow — §23 Status- und Freigabelogik / §21.5 Freigabeprinzip)
- **`tenant_approvals`** (db.py): `target_type` (strategy/portfolio/depot/profile), `target_id`, `status`, `approved_by`, `approved_at`, `note`. UNIQUE(tenant_id, target_type, target_id).
- **Zustände (§23):** `nicht_freigegeben` (Default) · `in_pruefung` · `freigegeben` · `gesperrt`.
- **`security.approval_set/get/list`** + **`enforce_approval(tenant, target_type, target_id)`** — nur `freigegeben` erlaubt Trading-Aktionen (PAPER_ONLY-Enforcement analog Phase 12).
- **UI:** `/admin/tenant-config` zeigt Freigaben-Sektion (Tabelle + Formular + Status-Toggle). Routen: `/api/approval` (GET), `/api/approval/set` (POST, TENANT_ADMIN), `/admin/tenant-config/approval` (POST), `/admin/tenant-config/approval/<id>/set`.
- **Tests:** Sektion 7m (+9) → 151 OK, 0 FAIL.

## [2.37.0] - 2026-08-09
### Added (PHASE 13 Code: Order-Intent + Broker-Adapter + Vier-Augen — Mandanten-Ausbauauftrag §10/§11)
- **`create_order_intent(...)`:** Jede geplante Order entsteht jetzt als Intent-Objekt mit allen 17 Pflichtfeldern (`order_intent_id` UUID, `tenant_id`, `user_id`, `portfolio_id`, `strategy_id`, `mode`, `ticker`, `side`, `quantity`, `order_type`, `limit_price`, `stop_price`, `reason`, `decision_id`, `rule_version`, `risk_check_status`, `created_at`).
- **`validate_order_intent(...)`:** 15-Check-Order-Risk-Liste — Modus-Gate (LIVE_* hart blockiert, PAPER_ONLY), PAUSED/SUSPENDED/REVOKED blockiert, Menge > 0, Markt offen, max. 20 Positionen, `enforce_risk_limits` (Position/Drawdown), `enforce_rules` (BLOCK/MAX_KAUF/REGEX).
- **`BrokerProvider`-Schnittstelle:** verbindliches Interface (`connect`, `disconnect`, `health_check`, `get_account`, `get_positions`, `get_quote`, `place_order`, `cancel_order`, `get_order_status`, `get_open_orders`) — Grundlage für spätere Sandbox-/Live-Adapter.
- **`PaperBrokerAdapter`:** Simulator (einziger implementierter Adapter, PAPER_ONLY) — führt Intents im Paper-Order-Buch aus (`paper_order_insert` + `paper_position_apply`, BUY/SELL, tenant-scoped).
- **`batch_trader.py`:** Kauf-Orders entstehen als Order-Intent **vor** jeder Ausführung; Verstoß → `INTENT-BLOCK` (nie fatal, PAPER_ONLY).
- **`four_eyes_required(action, requester, approver)`:** Vier-Augen-Freigabe für `live_request`/`live_approve`/`broker_connect`/`risk_limit_change`/`pause_resume`/`role_to_admin`/`backup_restore` — Antragsteller darf nie selbst genehmigen.
- **Doku:** `ORDER-RISK-CHECKLIST.md`, `BROKER-CONNECTOR-SPECIFICATION.md`, `PLATFORM-IMPLEMENTATION-REPORT.md`.
- **Tests:** Sektion 7l (+20) -> **144 OK, 0 FAIL**.

## [2.36.0] - 2026-08-09
### Added (PHASE 13: Mandanten-Config UI im `/admin`-Bereich)
- **`/admin/tenant-config`**: Risikogrenzen (beide Modi) + Regeln (effektiv Tenant ∪ global) verwalten.
- **Nav-Tab „🏢 Mandanten"** eingefügt.
- **Risiko-Formular** → `POST /admin/tenant-config/risk` (partial update, keine NULL).
- **Regeln**: Tabelle + Hinzufügen (`POST /admin/tenant-config/rule`) + Status-Toggle (`/rule/<id>/set?status=`).
- **Quell-Tags** (tenant/global/default) via `.src-*`-CSS-Klassen.
- **Tests:** ROUTE_ACCESS-Mapping ergänzt → **124 OK, 0 FAIL**.

## [2.35.0] - 2026-08-09
### Added (PHASE 12: Enforcement — Risikogrenzen + Regeln wirken im Trading-Pfad)
- **`enforce_risk_limits(tenant, mode, pos_pct, value, drawdown)`:** blockt Order wenn Position-Size oder Drawdown die effektiven Tenant-Limits überschreitet. Liefert `{allowed, reason, limits}`.
- **`enforce_rules(tenant, ticker, context)`:** wendet effektive Tenant-Regeln an — Typen `BLOCK:<text>` (hart blockiert), `MAX_KAUF:<n>` (max Käufe), `REGEX:<pattern>` (Ticker-Filter); nur Regeln mit Status `aktiv`.
- **`batch_trader.py`:** Risiko- + Regel-Check **vor jeder Kauf-Order** (PAPER_ONLY); Enforcement-Fehler sind nie fatal (Trading läuft weiter).
- **Tests:** Sektion 7k (+8) -> **124 OK, 0 FAIL**.

## [2.34.0] - 2026-08-08
### Added (PHASE 10+11: Tenant-Scoped Risikogrenzen + Regeln — Mandanten-Ausbauauftrag)
- **tenant_risk_limits Tabelle:** tenant-scoped Risikogrenzen pro Modus (moderate/aggressive).
- **effective_risk_limits(tenant, mode):** Tenant-Override → globaler `settings.json risk_parameter` → Default (kein NULL, nie globale Leakage).
- **tenant_rules Tabelle:** tenant-scoped Regeln.
- **effective_rules(tenant):** Tenant-Regeln ∪ globale `learned_rules.json` (Tenant gewinnt bei ID-Kollision).
- **db.py:** `risk_set/get/list`, `rule_set/list/set_status`; **security.py:** analoge Wrapper.
- **dashboard.py:** `/api/risk`, `/api/risk/set`, `/api/rules`, `/api/rules/add`, `/api/rules/set_status` (TENANT_ADMIN).
- **dashboard.html:** Mandant-Panel (Risikogrenzen + Regeln, nur Tenant-Admin).
- **Tests:** Sektion 7j (+8) -> **116 OK, 0 FAIL**.

## [2.33.0] - 2026-08-08
### Added (PHASE 9: Paper-Order-Buch — Mandanten-Ausbauauftrag)
- **paper_orders Tabelle:** tenant-scoped (`tenant_id`, `portfolio_id`, `ticker`, `side`, `quantity`, `price`, `status`, `order_type`), Index auf tenant_id.
- **db.py:** `paper_order_insert` (tenant-scoped), `paper_order_list` (optional nach Portfolio gefiltert), `paper_position_apply` (BUY erhoeht / SELL verringert Shares, Avg-Preis-Aktualisierung).
- **FIX:** `paper_portfolio_create` liefert jetzt die `lastrowid` (fehlender Return aus unvollendetem Edit behoben).
- **Tests:** Sektion 7i (+5) -> **108 OK, 0 FAIL**.

## [2.32.0] - 2026-08-08
### Added (PHASE 8: Secret-Store — Mandanten-Ausbauauftrag)
- **secret_store Tabelle:** tenant-scoped, `UNIQUE(tenant_id, secret_key)`.
- **Tenant-Isolation:** Secrets pro Tenant getrennt (kein globaler `.env`-Key mehr).
- **db.py:** `secret_set/get/list_keys`; **security.py:** `secret_set/get/list_keys`.
- **dashboard.py:** `/api/secrets` (GET, nur Schluessel), `/api/secrets/set` (POST, TENANT_ADMIN).
- **ROUTE_ACCESS:** 2 neue Routen auf TENANT_ADMIN.
- **Tests:** Sektion 7h (+6) -> **103 OK, 0 FAIL**.

## [2.31.0] - 2026-08-08
### Added (PHASE 7: Provider-Connection-Manager — Mandanten-Ausbauauftrag)
- **provider_connections Tabelle:** tenant-scoped, environment DEMO/PAPER/SANDBOX/LIVE.
- **Secrets NUR als Referenz** (`vault://...`), nie Klartext; API maskiert bei Ausgabe (`••••••••xxxx`).
- **db.py:** `provider_connection_add/list/test` + Migration (`created_by` Spalte).
- **dashboard.py:** `/api/providers` (GET), `/api/providers/add` (POST), `/api/providers/test/<id>` (POST, TENANT_ADMIN).
- **ROUTE_ACCESS:** 3 neue Routen auf TENANT_ADMIN.
- **Tests:** Sektion 7g (+5) -> **97 OK, 0 FAIL**.
- **PAPER_ONLY bleibt** — keine echten API-Calls.

## [2.30.0] - 2026-08-08
### Added (PHASE 6: Shadow->Paper Freigabe — Mandanten-Ausbauauftrag)
- **paper_eligibility():** prueft Voraussetzungen (Min-KI-Decisions, keine Regelkonflikte).
- **enter_paper():** erzwingt SHADOW->PAPER nur wenn eligible (ValueError sonst).
- **db.py:** `paper_portfolios` + `paper_positions` (eigenes virtuelles Depot, nicht mit Shadow mischen).
- **dashboard.py:** `/api/paper/eligibility` (GET), `/api/paper/enter` (POST, TENANT_ADMIN).
- **ROUTE_ACCESS:** 2 neue Routen auf TENANT_ADMIN.
- **Tests:** Sektion 7f (+8) -> **92 OK, 0 FAIL**.
- **PAPER_ONLY bleibt** — keine Live-Ausfuehrung.

## [2.29.0] - 2026-08-08
### Added (PHASE 5: Trading-Modi-Zustandsmaschine — Mandanten-Ausbauauftrag)
- **8 Zustaende:** SHADOW/PAPER/LIVE_REQUESTED/LIVE_APPROVED/LIVE_ACTIVE/PAUSED/SUSPENDED/REVOKED.
- **db.py:** `trading_mode_transitions` Tabelle (Sektion 8 Pflichtfelder), `MODE_TRANSITIONS`, `mode_log_insert`/`mode_log_list`.
- **security.py:** `get_trading_mode`/`set_trading_mode` (erzwingt erlaubte Transition, `ValueError` sonst), `trading_mode_history`.
- **dashboard.py:** `/api/trading_mode` (GET), `/api/trading_mode/set` (POST, TENANT_ADMIN), `/api/trading_mode/history`.
- **ROUTE_ACCESS:** 3 neue Routen auf TENANT_ADMIN.
- **Tests:** Sektion 7e (+12) → **86 OK, 0 FAIL**.
- **PAPER_ONLY bleibt** — keine Live-Ausfuehrung.

## [2.28.0] - 2026-08-08
### Added (PHASE 4: Mandantentrennung — Mandanten-Ausbauauftrag)
- **Depot-Datentraeger pro Tenant:** SQLite-Tabellen `depots`/`etf_depots`/`spec_depots` (tenant_id).
- **`_tenant_scoped_depot_files(tid)`:** scannt alle Depot-JSONs, filtert auf `tenant_id` (Default 1).
- **`data()` lädt nur Depots des aktiven Tenants** (kein globaler Mix).
- **API-Tenant-Scope:** `/api/ki_log` (nur Tenant-Einträge), `/depot_json` (403 bei Fremd-Tenant), `/api/db_query` (erzwingt Session-Tenant, schließt PHASE-0-Lücke).
- **db.py:** `query_trades`/`query_ki` tenant_id-Parameter, `depot_register`/`depot_list_tenant`.
- **Tests:** Sektion 7d (+5) → **74 OK, 0 FAIL**.
- **Doku:** MULTI-TENANT-SECURITY-TESTPLAN.md.
- **PAPER_ONLY bleibt** — kein Live-Code.

## [2.27.0] - 2026-08-08
### Added (Rollen-/Berechtigungsmodell, PHASE 2 Mandanten-Ausbau)
- **Effektive Rolle** (`security.py`): Membership-Rolle im Tenant gewinnt vor globaler User-Rolle — User kann in Tenant A `admin`, in Tenant B `user` sein.
- **`TENANT_ROLE_PERMISSIONS`**: tenant-bezogene Permissions (`tenant_view`, `tenant_trade_control`, `tenant_manage`, `tenant_members`, `tenant_delete`). `tenant_delete` nur superadmin.
- **Neue Zugriffsklasse `TENANT_ADMIN`**: `before_request` prüft gegen die effektive Rolle (statt globaler) und setzt den Tenant-Kontext aus der Session. Systemweite Routen (`/api/tenants*`, `/api/users*`) bleiben global ADMIN — Tenant-Admin erreicht sie NICHT (403).
- **Decorators**: `require_tenant_role(min_role)` + `require_permission(perm)` (Tenant-Kontext).
- **API**: `GET /api/roles` (Rollenkatalog, TENANT_ADMIN), `GET /api/me/permissions` (effektive Rechte), `/api/me` um `effective_role`/`tenant_permissions` erweitert.
- **UI**: Mein-Konto zeigt effektive Rolle im Mandant (Chip, wenn abweichend).
- **Doku**: `ROLE-PERMISSION-MODEL.md`.
- **Tests**: Sektion 7c (14 neue) → **69 OK, 0 FAIL**.

## [2.26.0] - 2026-08-08
### Added (Mandanten-Modell, PHASE 1 Mandanten-Ausbau)
- SQLite-Tabellen `tenants`, `tenant_memberships`, `workspaces` (idempotente Migration).
- `tenant_id`-Spalten auf `trades`/`ki_decisions`.
- Tenant-Kontext aus Session (OWASP: nie vom Client) via ContextVar.
- Admin-Routen `/api/tenants`, `/api/tenants/create`, `/api/tenants/<id>/members`.
- UI: Mandant-Anzeige im Mein-Konto-Tab.
- Doku: `TENANT-DATA-MODEL.md`; Tests Sektion 7b (10 neue) → 55 OK.

## [2.25.1] - 2026-08-08
### Removed
- Drawdown-Warnungsbalken (kein Mehrwert).

## [2.20.2] - 2026-08-08
### Fixed (Risk 70 kauft endlich)
- **`batch_trader.py` Budget-Filter** (Z116-117 + Z146-148): `kauf_budget = depot.bargeld * 0.8` → `depot.bargeld * params["position_size"] * 1.5`.
  - Vorher: Risk 70 mit $107 Cash hatte `kauf_budget=$85.78` → nur Riesen-Einzelpositionen (> $85) erlaubt → keine Small-Caps ($5-30) → keine Kandidaten → keine Käufe.
  - Nachher: `kauf_budget=$52.27` → Small-Caps kommen durch → KI entscheidet → Käufe möglich.
- **Verifiziert** (Ad-hoc-Test mit echten Indikatoren): Risk 70 `bewerte()` liefert 4 Aktien (SOFI/CLOU/LGI/TNDM), KI-Kandidaten da. Penny-Penalty greift (Small-Caps > Penny-Score).
- **Root-Cause war zweigeteilt:** (1) Budget-Filter zu eng + (2) `bewerte()` braucht Indikatoren (rsi/macd/bb/atr), sonst fällt alles unter `min_score=27`. Im echten `scan_markt` sind Indikatoren gegeben.

### Changed (vorher 2.20.1)
- (siehe 2.20.0 für strategie.py SSOT)

## [2.20.1] - 2026-08-07
### Fixed (strategie.py Selbsttest)
- Assertion `volumen_pos_size(0.20)` → `volumen_pos_size(0.10)` korrigiert (0.20 liegt zwischen Dämpfer-Stufen, korrekt 0.70). Selbsttest grün.

## [2.20.0] - 2026-08-07
### Added (Zentrale Strategie-Config)
- **Neue Datei `strategie.py`** (Single Source of Truth): Alle weichen Bewertungsregeln zentral.
  - `preis_score()`: Penny-Penalty (<$5 → -10), Small-Cap-Bonus ($5-30 → +8), Expensive (>$30 → +3)
  - `volumen_pos_size()`: Volumen-Dämpfer (0.3x→70%, 0.15x→40%, 0.08x→Verzicht)
  - `ist_hebel_etf()`: Hebel-ETF-Erkennung (Liste + Tier 3/4)
  - `STRATEGIE_HINWEISE`: KI-Prompt-Baustein (Volumen/Hebert/Tier-Mix)
- **Refactor:** `engine.bewerte()`, `etf_trader.etf_bewerte()`, `ki_decisions.STRATEGIE_HINWEISE` lesen jetzt aus `strategie.py` — keine hartcodierten Regelwerte mehr in den Modulen.
- **Konsistenz:** Penny-Penalty gilt jetzt für **Aktien + ETF + Spec** (vorher nur Aktien). Bug gefixt: ETF hatte altes "billig=mehr Score" Bias.
- **Verifiziert:** 3x Prüfung (Syntax/Import, Konsistenz, Verhalten+Integration) alle PASS.

## [2.19.7] - 2026-08-07
### Changed (Spec-Watchlist Masse)
- **`spec_watch.py` `WATCHLIST`**: 49 → **169 Ticker** (+120). Mehr Krypto/Leveraged/Volatility/Commodity/AI/EV/Biotech/Meme/Space/Fintech/Retail/Energy/Gaming/Cannabis. Ziel: KI hat pro Spec-Depot mehr Auswahl (Rotation/Diversifikation), ohne die Depot-Anzahl zu erhöhen (kein Klumpenrisiko durch mehr Depots).
- **`max_spec_depots` NICHT erhöht** (User: "nicht mehr Depots bei specs"). Die 49 bestehenden Depots bleiben, wählen aber aus 169 statt 49 Kandidaten.
- **Cron-Fenster**: Auswertungs-Crons auf 5-10 Min nach Börsenschluss (Audit 22:05, Monitor 22:17).

## [2.19.6] - 2026-08-07
### Changed (Risiko-Rampe Stufe 3: Penny-Penalty)
- **`engine.py` Z31-35**: Budget-Anpassung umgedreht (Hybrid b+c). Bisher: billigere Aktien kriegen MEHR Score (Penneys wie AMC $2.56 / WKHS $3.26 dominierten Top-10 bei $100-Cash-Depots → KI fand kein Signal → hielt). Neu: Aktien <$5 kriegen **Score-Abzug (-10)**, $5-30 Small-Caps **+8** (Diversifikation), >$30 **+3** (neutral). Penneys nicht ausgeschlossen (Pool bleibt voll), aber abgewertet.
- **Verifiziert**: Risk 70 Top-10 vorher 5 Penneys (<$5), nachher 10× $5-30 (CLOU $27, LGI $18, TNDM $22, EIDO $13, ACHR $5.5, PATH $15, CRSR $14, JKS $17, KSS $19, RELY $24). Bei $107 Cash + 37.5% Position = 2-3 kaufbare Positionen → echte Streuung.
- Kein Live-Geld — Shadow/Paper-Testsystem.

## [2.19.5] - 2026-08-07
### Changed (Risiko-Rampe Stufe 1+2)
- **Stufe 1 — Volumen-Filter geöffnet** (`ki_decisions.py` Z258-260): `vol_ratio <0.3x` → 70% Position (statt 50%); `<0.15x` → noch 40%; erst `<0.08x` = kompletter Verzicht (statt 0.15x). Ziel: mehr Käufe = mehr Lern-Signal.
- **Stufe 2 — Hebel-ETFs erlaubt** (`ki_decisions.py` Z261-263): 3x-Produkte (TQQQ/SQQQ/UVXY/VXX/VIXY/SOXS/SPXS/JDST/JNUG/FNGU/BOIL/UCO/SCO/NRGU/FAZ) dürfen gekauft werden, aber nur mit KLEINER Position (max 30% Cash) wegen Slippage/Vola. Kein generelles "halten" mehr.
- **Strategie:** Gestaffelte Risiko-Erhöhung ("wie Klaiber") — von sicher schrittweise öffnen, Ergebnis bewerten, bei Bedarf zurückdrehen (Backup + Git vorhanden).
- Kein Live-Geld — Shadow/Paper-Testsystem.

## [2.19.4] - 2026-08-07
### Changed (Strategie: Diversifikation)
- **`build_risk_profile.py` Z99-100**: `max_positions` 2-6 → **4-8** (Risk 0→8, Risk 95→4), `position_size` 0.30-0.60 → **0.15-0.40** (Risk 0→0.15, Risk 95→0.40). Ziel: mehrere kleine Positionen statt weniger teurer Klumpen.
- **`ki_decisions.py` Z252-260**: Prompt erweitert um STRATEGIE-HINWEISE — Volumen als Dämpfer (nicht als Hard-Stop, erst <0.15x illiquide), Diversifikation (max 1 Penny/Tier, Mix aus ≥2 Tiers), Bevorzugung von 3-5 kleinen Positionen. Gilt für ALLE Risk-Stufen.
- **`risk_profile.py`** neu generiert (1446 Zeilen).
- Kein Live-Trading während Testphase — nur Paper/Sim (wie bisher).

## [2.19.3] - 2026-08-07
### Fixed (Cash-Anzeige Risk-Depots)
- **`dashboard.html` Z616**: `dep.bargeld = dep.bargeld || 0` → `dep.bargeld = full.bargeld || 0`. Dashboard zeigte bei Risk-Depots (70-90) **CASH=$0.00** obwohl Depot $107–124 Cash hat. Root-Cause: bargeld wurde aus dem Overview-Objekt (`dep`) gelesen statt aus dem Detail-Response (`full`). Korrigiert auch `dep.wert`/`dep.start` auf `full.*`.
- Verifiziert: `/depot_json?risk=90` liefert `bargeld=123.96` → Dashboard zeigt jetzt `$123.96`.

### Echte Situation Risk 70–90 (KEIN Bug)
- Depots haben Cash ($107–124), KI läuft (ki_log.json: Entscheidungen heute 15:49 für MARA/LABU/UPRO/MRNA/JNUG/MSTR/VXX).
- KI empfiehlt **halten** (Marktlage: dünnes Volumen, Abwärtstrends in Kandidaten) → keine neuen Positionen.
- KI sieht im Prompt korrekt `bargeld=123.96` (batch_trader.laden_oder_erstellen liest bargeld aus JSON).
- Tracking-Note: spec-Depot-KI-Entscheidungen landen in ki_log.json unter `depot_typ="aktien"` (nicht `spec_XX`) → DB-Filter `spec_XX` findet 0. Kosmetisch, keine Kauf-Blockade.

## [2.19.2] - 2026-08-07
### Added (Trade→KI-Zuordnung — Infrastruktur)
- **`db._sync_trades`**: liest `decision_id` aus Depot-JSON-Trade (falls vorhanden, sonst NULL).
- **`db.match_trades_ki()`**: weicher Match Trade↔KI über Ticker + Zeitfenster (10min). Nur **eindeutige** Zuordnungen (1 KI im Fenster) werden gesetzt; sonst NULL (ehrlich, keine Erfindung). Direkter Key (`trade.decision_id == ki_decisions.decision_id`) hat Vorrang.
- **`db.sync()`**: ruft `match_trades_ki()` nach dem Sync auf.
- **`db.analyse_karten`**: `trades_mit_decision_id` + `trades_ohne_ki_zuordnung` (weicher Match) jetzt echt aus DB.

### Ehrlichkeits-Hinweis (wichtig)
- Bei **aktuellen/alten Daten** (vor v2.19.1) haben weder Trades noch ki_decisions eine `decision_id` → weicher Match findet zwar Ticker/Zeit-Treffer, aber KI-Seite `decision_id=NULL` →Trade bleibt NULL.
- Bei **neuen Läufen** (ab v2.19.1): `ki_decisions.decision_id` wird befüllt → weicher Match ordnet sie den Trades zu.
- **Offener Punkt:** `batch_trader.py`/`spec_trader.py` schreiben beim Trade-Export noch keine `decision_id` in Depot-JSON. Das ist ein größerer Umbau (decision_id durch Aktions-Pipeline tragen) → eigener Auftrag. Bis dahin: weicher Match als best-effort.

### Verifiziert
- `match_trades_ki()`: idempotent, 1 weicher Match bei aktuellen Daten (ki-Seite NULL → Trade NULL, ehrlich).
- `analyse_karten`: `trades_mit_decision_id=0/927` (korrekt für alte Daten).

## [2.19.1] - 2026-08-07
### Added (Audit-Felder — echte DB-Spalten)
- **DB-Schema-Migration** (`db._migrate_schema`, idempotent): `trades` + `ki_decisions` erhalten `decision_id`, `provider`, `regel_id`, `fallback` (TEXT, nullable). Bereits vorhandene Spalten werden übersprungen.
- **`ki_decisions.py`**: `entscheide_ticker` schreibt jetzt `provider` (welcher Free-Tier-Provider entschied) + `fallback` (True bei KI-Crash → sicheres `halten`, False bei echter KI-Entscheidung). Schon vorhanden: `decision_id` (immer erzeugt), `angewandte_regeln[].id` (→ `regel_id`).
- **`db._sync_ki`**: liest `decision_id` + `regel_id` aus `ki_log.json` beim Sync.
- **`db.analyse_karten`**: `entscheidungen_mit_decision_id`, `legacy_fallbacks`, `provider_fehler`, `provider_verteilung`, `entscheidungen_mit_regel` jetzt **echt aus DB** (nicht mehr `n/a`).
- **Analyse-Tab analyse2**: Filter Provider + Fallback (Echte KI / ⚠FB) + neue Spalten (Provider/decision_id/Regel-ID) + Karten mit Provider-Verteilung.
- **`report_pdf._datenvertrauen`**: `decision_id-Zuordnung` ehrlich aus DB (z.B. "vollständig (22% der Einträge)" oder "Legacy (alte ohne Feld)").

### Ehrlichkeits-Hinweis
- Alte 178 ki_decisions (vor v2.19.1) haben **kein** decision_id/provider (aus Zeit vor Feld-Einführung) → in DB NULL, nicht erfunden. Nur neue Entscheidungen (ab jetzt) befüllen die Felder.
- `trades.decision_id` (Trade→KI-Zuordnung) bleibt offen: Depot-JSONs haben kein decision_id → Match folgt in eigener Migration.

### Verifiziert
- DB-Migration idempotent (2x sync = keine Duplicate-Spalten).
- `/api/db_karten`: `entscheidungen_mit_decision_id=0/178` (ehrlich, alte Daten), `provider_fehler=178` (alle unknown, alt).
- `/api/db_query?mode=ki&provider=zen` Filter funktional.

## [2.19.0] - 2026-08-07
### Added (Analyse- & Datenvertrauen-Stabilisierung)
- **Phase B — Datenvertrauens-Score**: Tagesbericht zeigt `DATENLAGE: HOCH|MITTEL|NIEDRIG|NICHT VERIFIZIERT` + 9 Statusfelder (Portfolio-Snapshot, Trade-Daten, Einzel-Trade-P&L, Gebühren, Slippage, Drawdown, decision_id-Zuordnung, KI-Provider, Report-Erzeugung). Kein erfundenener %-Wert.
- **Phase C — Statusübersicht**: Tabelle Produktiv/Shadow/Konzept/Offen (US/Aktien/ETF/Spec=PRODUKTIV; DE/JP/Profile=KONZEPT; Paper/Live-Freigabe=OFFEN; WhatsApp=EINGESCHRÄNKT).
- **Phase D/F — 9-Seiten-PDF**: Seite 1 Tagesstatus+Datenvertrauen, S2 Kategorien/Verlauf, S3 Performance/KI-Lernen, S4 Statusübersicht+Root-Cause-Historie, S5-9 Detail (Tagesstatus/Performance/Risiko/Trades/Governance/System).
- **Phase E — Analyse-Tab analyse2 erweitert**: API `/api/db_karten` liefert Kennzahlen (Trades/KI/K-V-H-Verhältnis/Konfidenz-Schnitt). Dashboard zeigt Karten. decision_id/Provider/Legacy ehrlich als `n/a` (DB-Feld fehlt).
- **Phase G — KI-Provider-Stabilität**: Transparente Tabelle im PDF (5 Provider, Cooldown-Status, Konfiguration).

### Unverändert (bewusst)
- DB-Schema: keine `decision_id`/`provider`/`regel_id`/`fallback`-Felder → im Report als `n/a`/`Legacy` markiert (ehrlich, nicht erfunden).
- Keine neuen Märkte/Profile/Live-Automatisierung (außerhalb dieses Auftrags).

### Fixed
- `anLaden2` korrupter Text (`l sucrose...`) → `lädt...`.
- JS `node --check` valid (kein SyntaxError).

### Verifiziert
- PDF-Generierung: 9 Seiten, 264KB, Datenvertrauens-Sektion + Statusübersicht + Root-Cause-Tabelle gerendert.
- API `/api/db_karten`: trades=927, ki=178, K/V/H=140/102/138, Konfidenz=56.5%.

## [2.18.3] - 2026-08-06
### Changed
- **KI-Wellen (gestreckte Calls)**: KI-Taktung auf 30min zurück (statt 120), aber Calls gestreckt statt gebündelt. Scheduler triggert `ki_welle` alle 30min mit `--welle 0-3` (rotierend), jede Welle verarbeitet nur 13 der 49 Spec-Ticker. Ursache Rate-Limit (zen Free-Tier 429 nach ~20 Calls): 49 Calls auf einmal. Jetzt ~13/Welle → zen hält durch, andere Provider springen ein. Verifiziert: Welle 0/1 laufen sauber, nur zen rate-limited.

### Fixed
- **PDF falsche Gesamt-Zahlen (erneut)**: `lade_depots_flat()` ignorierte leere Aktien-Depots (0 Positionen) komplett → deren Startkapital (3×100$=300) fehlte in Aktien-Summe (1400 statt 2000) → Gesamt-PnL falsch (~+0,02% statt echter +0,92%). Fix: leere Depots als reines Startkapital in Bilanz aufgenommen. Version-Hardcode in PDF auf `version.json` (2.18.3) korrigiert. Verifiziert: Aktien +4,65%, Gesamt +0,92%.

## [2.18.2] - 2026-08-06
### Changed / Added
- **Scheduler intelligent getaktet**: Engine (Daten-Sammeln) alle 15min, KI-Trading (Entscheidungen) nur alle 60min (`MT_KI_INTERVAL=60`). Root-Cause: 26 volle KI-Läufe/Tag × ~90 Calls = 2340 Calls/Tag → zen Free-Tier Rate-Limit (429) voll → KI-Trading tot. Jetzt ~6 KI-Läufe/Tag = ~540 Calls (unter Limit).
- **Integritätsprüfung** (`pruefe_pipeline_ergebnis`): warnt bei Cooldown-Blockade, 0-Kursen, nur-"halten"-Fallback oder Timeouts im Log.
- **NEU: SQLite-Analyse-DB** (`micro_trader.db` + `db.py`): spiegelt alle JSON-Depots nach jedem Pipeline-Lauf. Schnelles Auslesen + Quer-Analysen (`trades`, `ki_decisions`, `depot_snapshot`, `markt_daten`). Verifiziert: 925 Trades in DB.

## [2.18.1] - 2026-08-06
### Fixed
- **KRITISCH: KI-Trading war lahmgelegt** — Root-Cause 1: alle 5 Provider im Circuit-Breaker-Cooldown (`ki_cooldown.json`) wegen hängengebliebenem State vom Hermes-Modell-Wechsel. Root-Cause 2: Reasoning-Modelle (nous-hy3/step) lieferten bei kleinem `max_tokens` KEIN `content` → `_ki_call` wertete das als Fehler → Cooldown "timeout". Fix: `CALL_TIMEOUT` 120→180s, Cooldown-Datei >6h auto-verworfen, `_ki_call` akzeptiert `reasoning_content` + leere Antworten lösen KEINEN Cooldown, `ki_cooldown.json` geleert. hy3 bleibt in Rotation (braucht `max_tokens>=1024` im Trader-Prompt, gegeben).
- **Spec-Trader final gefixt**: Workers 3→8 + Pipeline-Timeout 300→600s. Lief vorher bei 300s-Limit ins Timeout, brach mitten in KI-Calls ab → Orders blieben aus. Jetzt: 93-106s sauber durch (OK).
- **Verifiziert**: KI entscheidet echte kaufen/verkaufen, `ki_log.json` vollständig, kein Cooldown mehr.

## [2.18.0] - 2026-08-06
### Added
- **Phase 13: Live-Freigabe** (§29.F): Profile us_shadow/de_shadow/jp_shadow auf `modus=live` aktiviert via `freigabe.py --activate --confirm` (User-Freigabe erteilt 06.08.2026 20:31). Pre-Flight-Check bestanden. 29 Regeln (27 Meta-Caps + 2 Anti-Hold) bleiben bewusst Shadow. Dashboard-Profil-Karten zeigen `status=live`.
- **Tagesauswertungs-PDF (6 Pflichtsektionen)**: `report_pdf.py` erweitert — Tagesstatus, Performance/P&L, Risiko/Exposure, Trades/Ausführung, KI/Regel/Governance, Systemstatus/Anomalien/Audit. Report-ID (`RPT-YYYYMMDD-NNN`) + Audit-Fußzeile (KI GENERIERT, Seitenzahl) auf jeder Seite. Dateiname: `daily_report_YYYY-MM-DD_v<VERSION>_<RPT-ID>.pdf`.
- **Neue 9-Seiten-Struktur**: S1 Portfolio/Tag, S2 Kategorien, S3 Performance/KI-Lernen (endet nach Marktregime), S4 Projektstatus (getrennt!), S5-9 Tagesauswertung-Detail.
- **Live-Kurse in PDF**: `lade_depots_flat()` nutzt `marktdaten.hole_kurs()` (4-Tier-Fallback) statt nur `avg_price`.
- **Version zentral aus `version.json`** (kein Hardcode mehr).

### Fixed
- **KRITISCH — Falsche PDF-Werte** (User gemeldet): `lade_depots_flat()` rechnete ETF-/Aktien-Positionen OHNE Depot-Bargeld (`wert = shares*kurs` statt `bargeld_anteil + shares*kurs`) → künstliches Minus (-10,41% statt +0,97%). Fix: Cash-Anteil pro Position, wie das Dashboard.
- **Warnstatus-Falsch-Positiv**: Positive "Risk 50-95: +Rendite"-Meldungen zählten als Warnung → Seite 5 zeigte WARNUNG trotz STABIL. Fix: nur echte Warnungen (❌/gesperrt/Drawdown/Fehler).
- **Verwaiste Überschrift Seite 3**: "3.3 Marktregime" stand allein am Seitenende, Text auf S4. Fix: `KeepTogether`.
- **KI-JSON-Parse-Crash** (Bug 2): `json.loads` auf ungültiges JSON crashte unhandled → K:0-Trades. Fix: `try/except` + 1× Retry mit strikterem Prompt + Fallback `halten K:50`.
- **Anti-Hold-Ping-Pong** (Bug 1): Anti-Hold-Regeln (`VERBOT/MEIDE`, wirkung=verbot) erzwangen sofortigen Verkauf nach Kauf. Fix: `VORSICHT/ABWÄGEN`, wirkung=gewichtung, `durchgesetzt=False` — KI entscheidet final, Regeln als Kontext.
- **KI-Rate-Limit**: `entscheide_spec_batch` max_workers 12→3 (weniger gleichzeitige Calls gegen Nous-free-Quota).
- **`undefined` in Trade-Historie**: Depot-Trades hatten `aktion`, nicht `typ` → Dashboard zeigte `undefined`. Fix: 336 Trades migriert (`aktion`→`typ`) + Frontend-Fallback `t.typ || t.aktion || "?"`.
- **Leere ETF/Spec-Depots**: 19 Spec (bargeld=0) + 17 ETF (falsch gesperrt) repariert via `reparatur_depots.py` (Reset auf 100$, Unlock bei DD<30%).

### Verified
- PDF: Gesamtwert ~8.785$ / +0,97% (konsistent mit Dashboard +0,96%), 9 Seiten, keine Überläufe, Version v2.18.0 überall.
- ETF-Depots: 0 gesperrt, 20/21 mit Positionen. Spec: 0 leer.
- KI liefert echte Entscheidungen (K:55-60) via Hermes-Nous-Verbindung.

## [2.17.0] - 2026-08-06
### Added
- **Banner/Logo in Dashboard**: `assets/banner.png` + `logo.png` + `logo.ico`, Banner-Header in `dashboard.html` (height:90px, object-fit:contain), ASCII-Banner + Titel in `dashboard.bat`, README-Banner.
- **Dashboard Asset-Route**: `static_folder=assets` + explizite `/assets/<path>` Route via `send_file`.
- **PDF v5**: Banner/Logo, Cyan/Violett/Mint-Farbwelt, Kategorie-Graphen.

### Fixed
- **/assets/banner.png 404**: Alte 5300-Instanz (PID 22740) lief mit altem Code im RAM → gezielter `taskkill` + frischer Start.
- **Banner falsch platziert**: `object-fit:cover`+`max-height:96px` clippte Text → `object-fit:contain`+`height:90px`+`background:#0b1220`.

### Verified
- HTTP 200 für /, /assets/banner.png, /assets/logo.png, /assets/logo.ico auf 5300.

## [2.16.12] - 2026-08-05
### Fixed
- **7 leere Spec-Depots gelöscht**: LABU, MARA, MNMD, QQQ, SOXS, TQQQ, VXX (0 Trades, 0 Pos, Cash übrig). KI hielt bewusst (Hebele/Volatility per Anti-Regel, MNMD delisted) → blockierten Spec-Übersicht. Nur 42 aktive Spec-Depots übrig (alle mit Trades/Positionen). Backup: `.backup/spec_empty-*`.

### Verified
- Spec-Depots: 42 (alle aktiv, keine leeren mehr)

## [2.16.11] - 2026-08-05
### Fixed
- **38 tote Spec-Depot-Dateien gelöscht**: Nicht in WATCHLIST, `start=0` (wertlos). Verzerrten Spec-Tab-Ansicht. Nur 49 gültige Spec-Depots übrig (alle in WATCHLIST). Backup in `.backup/spec_depots-dead-*`.

### Verified
- Spec-Depots: 49 (alle in WATCHLIST, keine toten Placeholder mehr)
- Dashboard `data().spec_depots` filtert korrekt (Platzhalter ohne Startkapital)

## [2.16.10] - 2026-08-05
### Added
- **spec_trader.fetch_analyse() Super-Mix-Fallback** (v2.16.10): Wenn yfinance im Batch einen Ticker auslässt (Flakiness) → Single-Download + `marktdaten.hole_kurs()` (4-Tier). Rettet z.B. MNMD (delisted, $0.69 via marktdaten).
- **`_MAX_SPEC`-Limit-Fix**: `tickers[:_MAX_SPEC]` schnitt QQQ ab (49 Ticker > Limit 48). Jetzt `max(_MAX_SPEC, len(tickers))` → kein Ticker mehr verloren.
- **RSI-Berechnung robuster**: `try/except` + NaN→50.0 Fallback (verhinderte QQQ-Crash im Loop).

### Fixed
- **ETF-Depots systematisch tot** (P55-Altlast): 20 ETF-Depots hatten `bargeld 8–72$`, `shares=0` (0$-Verkauf zerstörte sie). Reset auf `bargeld=100, start_wert=100, shares=0` + ungültige 0$-Trades entfernt. `etf_trader` füllt sie jetzt wieder (VGK/VEA/VWO/SCHD/ARKK/XLF <100$ kaufbar).
- **7 leere Spec-Depots**: JOBY/LABU/MARA/QQQ/RKLB/SOXS/TQQQ/VXX bekamen keine KI-Entscheidung (yfinance-Batch-Flakiness + QQQ-Limit-Bug). Jetzt alle 49 Ticker in `fetch_analyse()` → KI entscheidet (Hebele/Volatility bewusst "halten" via Anti-Regeln).

### Verified
- `fetch_analyse()`: 49 Ticker (alle 8 leeren Spec + QQQ da)
- ETF-Reset: 20 Depots auf 100$ (keine Toten mehr)
- Spec-Trader: 49 KI-Entscheidungen/Run (vorher ~40 durch Abstürze)
### Fixed
- **Spekulations-Depots kauften nie** (39 leere Spec-Depots mit Cash): Root-Cause in `ki_decisions.entscheide_ticker()` — bei `shares=0` stand nur `POSITION: Keine Position`, kein Kauf-Hinweis → KI hielt konservativ. Fix: `[LEER: BITTE KAUFEN — {bargeld}$ Cash verfügbar, Ticker ist in Watchlist!]` bei `bargeld >= 20$`.
  - **Ergebnis**: 18 Spec-Depots mit neuen Käufen (ASTS 1.47st @$68, BB 12st @$8.90, COIN 0.66st @$152, CRSP, GME, IBIT, MSTR, RIVN, RGTI etc.).
  - **Bewusst erhalten**: Volatility-/Hebele-ETFs (UVXY, SQQQ, SOXS, TNA, UPRO, VIXY) weiterhin per gelernter Anti-Regel geblockt (nicht blind kaufen).

### Verified
- Unit-Test: ASTS (leer, $100, Kurs $68.27) → KI sagt "kaufen" (K:60)
- Spec-Trader Run: 9 non-Hold, 18 Kauf-Trades in Depot-Dateien

## [2.16.8] - 2026-08-05
### Added
- **Super-Mix Datenquellen** (`marktdaten.py` neu): Live-Kurs via 4-Tier-Fallback
  yfinance → Finnhub `/quote` (60/min) → TwelveData `/quote` (800/day) → AlphaVantage `GLOBAL_QUOTE` (25/day).
  Löst das yfinance-Rate-Limit-Problem (Kurs = 0 → P55-Crash bei Verkauf).
- **Scan-Resilienz**: `scan_markt()` yfinance-Primary, bei Exception/leerem DataFrame TwelveData `time_series` als Fallback (begrenzt auf 50 Ticker/Run, da 800 credits/day).
- **`.env`** mit `FINNHUB_KEY`, `TWELVEDATA_KEY`, `ALPHAVANTAGE_KEY` (Keys nicht im Repo — `.gitignore` ergänzt).

### Fixed
- **Leere Depots kauften nie** (Risk 65/70/80/85/90): Root-Cause war Feldname-Bug — `bewerte()` liefert `preis`, aber `batch_trader.py` las `aktuell` → alle Kandidaten Preis 0 → fielen durch Budget-Filter → KI sah "keine Kandidaten" → hielt. Fix: `alle_kandidaten` liest `t.get("preis", 0)`.
  - **Ergebnis**: Risk 65/80/85/90 kaufen jetzt LCID/AMC/DOMO/SOXS (alles im Budget).

### Verified
- Unit-Test: yfinance deaktiviert → Finnhub liefert AAPL 309.80, LCID 6.65 (Fallback greift)
- Live-Test: AAPL 309.76, LCID 6.63, AMC 2.71 (yfinance-Primary)
- KI-Batches: 4×5 Depots, zen-nemotron stabil, leere Depots mit Kauf-Aktionen

## [2.16.7] - 2026-08-05
### Fixed
- **ETF-Depots kauften nie**: `etf_bewerte()` gab nur Top 3 Kandidaten — wenn die alle teurer als das $100-Budget waren (z.B. Risk 25: DIA $544/SPY $775/VTI $382), ergab `menge = int(bargeld/preis) = 0` → `continue` → kein Kauf. etf_025 blieb ewig leer.
  - Fix 1: Preis-Malus in `etf_bewerte()` (preis > budget → Score -40) → bezahlbare ETFs ranken höher.
  - Fix 2: `return erlaubt[:8]` statt `[:3]` → Kauf-Loop erreicht bezahlbare Alternativen.
  - **Ergebnis**: etf_025 kaufte VGK 1st @$92.07 (Rest $7.93) — alle 20 ETF-Depots haben jetzt Positionen.
- **Back-Button in Depot-Detailseiten**: `showTab('overview')` war hartcodiert → nach "← Zurück" landete man immer auf der Übersicht, egal aus welchem Tab. Fix: `showTab(typ === 'main' ? 'overview' : typ)` → zurück in Aktien/ETF/Spec-Tab.
- **ETF-Karten-Klick ging nicht**: `JSON.stringify(e).replace(/\\\"/g,...)` (4 Backslashes im Source) matchte fast nie → rohe `"` im onclick → Attribut brach. Fix: 2 Backslashes wie in `renderCard` → Karten öffnen Detailseite.

### Verified
- etf_025: VGK-Position, 1 Trade, HTTP 200
- Back-Button: ETF-Karte → Detail → Zurück → Tab = 📦 ETF (nicht mehr Übersicht)
- ETF-Karten: `showDepot({&quot;cash&quot;:8.32,...})` korrekt escaped

## [2.16.6] - 2026-08-05
### Changed
- **Summary-Chips vereinheitlicht** (Spec-Tab): Die doppelte summary-row unten im spec-overview-Pane (Gesamtwert/Ø-Rendite/Aktive Pos./Beobachtet) entfernt — war ein Relikt aus v2.11.1-Umbau. Alle 6 Stats jetzt in EINER Row oben: Gesamtwert, Rendite, Depots, Trades, Bester, Schlechtester. 24h-Widgets (Top-Gewinner/Verlierer) bleiben unten.
- **Aktien- & ETF-Tab**: Bester/Schlechtester-Chips ergänzt (fehlten dort) — Aktien/ETF zeigen "Risk X +Y.Z%" bzw. "Risk X -Y.Z%", Spec zeigt Ticker.
### Verified
- Spec: Oben 6 Chips, Unten-Duplikat weg (grep Spec-Gesamtwert = 1 statt 2)
- Aktien: $2116 · +5.81% · 20 · 14 · 189 · Risk 90 +20.3% · Risk 65 -2.6%
- ETF: $2014 · +0.69% · 20 · Risk 95 +10.8% · Risk 90 -7.8%

## [2.16.5] - 2026-08-05
### Fixed (kritisch)
- **Depot-Crash durch Verkauf zum Preis 0**: yfinance-Rate-Limit (YFRateLimitError) liess `hole_kurs_fuer()` 0 liefern → KI-Verkauf mit `preis=0` → `erlös=0`, Position geloescht ohne Bargeld-Gutschrift → Depot-Werte stuerzten um bis zu -92% in Minuten. Betroffen: 14 Depots (DOMO, ASTC, AA, ALKS, CVM, CIFR).
  - `batch_trader.py`: Verkauf wird uebersprungen wenn Kurs <= 0 (Position bleibt).
  - `engine.py`: gleicher Schutz in `ausführen()`.
- **Daten-Restore**: 14 zerstörte Depots aus Dev-Clone wiederhergestellt (Positionen + Entfernen der preis-0-Trades). Backup: `.backup/depot-restore-20260805_155305/`.
- Scheduler neu gestartet mit Fix.

### Lesson
- Nie einen Trade mit Preis <= 0 ausfuehren — lieber Position behalten als zu 0 verkaufen.
- Rate-Limit von yfinance ist ein bekanntes Risiko: `hole_kurs_fuer()` muss bei Fehler `None` (nicht 0) liefern und Aufrufer muessen das pruefen.

## [2.16.4] - 2026-08-05
### Fixed
- **Profilwechsel jetzt sofort sichtbar**: `data()` cached das Dashboard-Ergebnis 60s — `/api/profile?set=` hat den Cache nicht invalidiert, daher zeigte das Dropdown nach Wechsel bis zu 60s das alte Profil ("wechselt aber nicht"). Fix: Cache-Invalidierung (`data._cache = None`) nach erfolgreichem Wechsel.
- **Import-Fix**: `_profil_info()` importierte `lade_aktives_profil` — Name jetzt konsistent mit `profile_schema.py` (Funktion existierte, nur Referenz falsch). Root-Cause via `traceback.print_exc()` im except sichtbar gemacht.

# Micro-Trader DEV — CHANGELOG

> Entwicklungs-Zweig (Clone von Produktiv). Port 5400. Produktiv (5300) bleibt unberührt.
> Reihenfolge gemäß Zielarchitektur §28 (von innen nach außen).

## v2.16.3 "Profil-Modell" (2026-08-05 14:00) — DEV
**👤 Phase 2 (Identität & Struktur): Profil-Schema + US_Test_Shadow**

- **NEU `profile_schema.py`**: `Profil`-Klasse + JSON-Schema-Validierung + Default `US_Test_Shadow`
  (US-Markt, Shadow-Modus, USD, Aktien/ETF/Spec).
- **NEU Route `/api/profile`** (dashboard.py) + `profil` in `data()`.
- **NEU Profil-Karte** im Übersicht-Tab (Name/Modus/Base-Währung/Märkte/Depotarten/Version).
- Reine Metadaten-Hülle — greift noch **nicht** steuernd in Trading ein (folgt Phase 3+).
- **Verifiziert:** `/api/profile` liefert Profil, `/data` profil-Block, HTTP 200, Produktiv (5300) unberührt.

### Dateien geändert (nur Dev-Clone)
- `profile_schema.py` — NEU
- `dashboard.py` — `/api/profile` + `_profil_info()` + `profil` in `data()`
- `dashboard.html` — Profil-Karte im Übersicht-Tab
- `profile.json` — auto-erstellt (US_Test_Shadow)
- `version.json` — v2.16.3

### Nächster Schritt (Phase 2 weiter)
- [ ] Profil-Wechsel (mehrere Profile anlegen, aktives Profil umschalten)
- [ ] Profil in Scheduler/Trader einbinden (Phase 3: Marktmodell nutzt profil.märkte)

### Profil-Wechsler (Phase 2 Erweiterung, 2026-08-05 14:10)
- **Mehrfach-Profile:** `profile_US_Test_Shadow.json`, `profile_DE_Test_Shadow.json`,
  `profile_JP_Test_Shadow.json` (DE/JP als Platzhalter für Phase 3).
- **`active_profile.json`** steuert das aktive Profil (via `setze_aktives_profil()`).
- **Route `/api/profile?set=<name>`** wechselt Profil. **`/api/profile`** listet verfügbare.
- **Wechsel-UI** im Dashboard (Dropdown in Profil-Karte).
- **Verifiziert:** Wechsel US→DE→US funktioniert, alle 3 Profile gelistet, `aktiv` korrekt.
- **Hinweis:** Flask-Modul-Cache! Nach Änderung an `profile_schema.py` Dashboard neu starten,
  sonst alter Code im Cache (hat Debugging verzögert).

### Nächster Schritt (Phase 2 → Phase 3)
Phase 2 abgeschlossen (Profil-Modell + Wechsler). Nächstes: **Phase 3 (Marktmodell)** nutzt
`profil.märkte` steuernd (Scheduler/Trader filtern nach aktivem Profil). Dann zurück in Produktiv.


### Profil-Wechsel Bugfix (2026-08-05 14:45)
- **Symptom:** Dropdown-Wechsel bestätigt, aber Profil blieb gleich (US_Test_Shadow).
- **Root-Cause:** `_profil_info()` in `dashboard.py` nutzte `lade_profil()` (Default),
  ignorierte `active_profile.json`. `data()` lieferte immer das Default-Profil →
  Dropdown zeigte falsche `selected`-Option.
- **Fix:** `lade_profil()` → `lade_aktives_profil()` in `_profil_info()`. Jetzt liest
  `data().profil` das aktive Profil → Wechsel sichtbar.
- **Verifiziert (Browser + curl):** Wechsel US↔DE↔JP funktioniert, Dropdown springt mit.
