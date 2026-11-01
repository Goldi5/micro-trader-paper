# Micro-Trader — Projekt-Dokumentation

> **Version:** v2.44.8 „Calm Trading Foundation — UI-Redesign Phasen 2–13 (komplett)" (2026-08-09)
> **Status:** Produktiv, Cron läuft, PAPER_ONLY (kein Echtgeld)
> **Letztes Update:** 2026-08-09 21:15

## 📌 Was ist das?
Papier-Trading-System mit KI-Lernen. 3 Kategorien:
- **Aktien:** 20 Depots (Risk 0–95, à $100 Start)
- **ETF:** 20 Depots (Risk 0–95, à $100 Start, 5 Stufen)
- **Spekulation:** 49 Watchlist-Depots (à $100 Start, Leverage/Volatility/Meme/etc.)

Plus KI-Lernmodul (learned_rules.json), Skill-Sync, Audit-Trail, **Tagesauswertungs-PDF** (täglich 22:00 via Pipeline).

## 🎨 UI-Designsystem (Calm Trading Command Center)
- **Hintergrund:** `#f7f9fc` (hell), **Flächen:** opak weiß (`#ffffff`), **kein** Glassmorphismus
- **Primärfarbe:** `#2563eb` (Slate-Blau), Dark-Varianten `#1d4ed8`
- **Topbar:** dunkel, 56px, Logo + 8 Hauptbereiche + Suche + User-Menü
- **8 Hauptbereiche:** Übersicht, Portfolios, Märkte, Analyse, Aktivität, KI, System, Einstellungen
- **Drawer:** Slide-in (480px rechts) für Depot-Details, Escape-Close, ARIA `role="dialog"`
- **Max. 4 KPI-Karten** auf Startseite, **max. 6 Portfolio-Karten** in der Übersicht
- **Responsive:** Media-Queries 1200/1024/768/480px; Tabellen scrollen horizontal
- **Accessibility:** Skip-Link, `role="main"`, `role="button"` + Keyboard-Handler auf Karten, `:focus-visible`-Outline
- **Design-Regel:** ausschließlich UI/Layout/IA geändert — **keine** Trading-/KI-/Risk-/Security-/Tenant-Logik

## 🚀 Schnellstart
```bash
cd ~/projects/micro-trader
"/c/Program Files/Python312/python.exe" dashboard.py 5300   # Dashboard (http://127.0.0.1:5300)
# Cron (Hermes): micro-trader-pipeline.py --mode ki, alle 15min, 300s/Timeout
```

## 📂 Struktur
| Datei | Zweck |
|-------|-------|
| `dashboard.py` | Flask-API + `data()`-Payload (Rendite, Verlauf, Historie) |
| `dashboard.html` | Frontend (Apple-Glass Optik, SVG-Charts, Tabellen) |
| `batch_trader.py` | Aktien-Trading (KI via ki_provider Fallback-Kette) |
| `etf_trader.py` | ETF-Trading (regelbasiert, keine KI) |
| `spec_trader.py` | Spec-Trading (KI via ki_provider, 48 Depots) |
| `ki_decisions.py` | KI-Entscheidungslogik (Einzel + Batch + Spec) |
| `ki_learning.py` | KI-Lernmodul (Regeln aus Entscheidungen) |
| `ki_provider.py` | **Provider-Fallback-Kette** (zen→nous-step→nous-hy3→openrouter) |
| `learned_rules.py` | Regel-Engine (shadow/freigabe_status, Versionierung) |
| `boersen.py` | Börsenzeiten (ist_offen, next_open) |
| `version.json` | Versions-Historie (CHANGELOG-Quelle) |
| `backup.py` | **Regel #1:** `backup.py before` / `after` vor jeder Änderung |

## 🔑 Wichtigste Konzepte

### Regel #1 (unverhandelbar)
**Vor JEDER Datei-Änderung:** `backup.py before "Beschreibung"` → danach `backup.py after "..."`.  
Rollback: `backup.py restore <id>`. ~40 Backups heute, keines verloren.

### KI-Provider-Fallback (v2.12.0)
Batch-Trader nutzt `ki_provider.call_ki()` → Kette:
```
zen (deepseek-v4-flash-free) → nous-step → nous-hy3 → openrouter
```
**OpenAI ist komplett raus** (Konto leer, 429). Bei 401/429/Timeout springt automatisch weiter.  
→ `ki_provider.py` ist die einzige Wahrheit für KI-Calls.

### 7-Tage-Verlaufsgraphen (v2.11.x)
- Backend: `portfolio_verlauf(tage=7)` in `dashboard.py` → 4 Serien (gesamt/aktien/etf/spec)
- Rendite gegen Startkapital: Aktien 2000 + ETF 2000 + Spec 4800 = **8800$**
- Frontend: SVG-Line-Chart (36px Übersicht, 32px Tabs), letzter Punkt = Live-Wert (v2.11.3)

### Spec-Trader Performance (v2.12.2)
- **Problem:** 1 KI-Call = ~8s (nous-step), 48 Depots = 6,4min → Cron (timeout=300) killte ihn vor system_log-Schreiben
- **Fix:** `max_workers` 8→12 + Cron-Timeout 300→600s
- **Getestet:** Lauf 371s, EXIT=0, schreibt ins system_log ✓

### Börsenzeiten
- NYSE/NASDAQ: 09:30–16:00 ET = **15:30–22:00 MEZ**
- Spec-Trader/Batch nur bei `us_offen` (Cron prüft `boersen.ist_offen("US")`)

## 📊 Dashboard-Tabs
| Tab | Inhalt |
|-----|--------|
| Übersicht | Summary + Portfolio-Verlauf (7T) + KI-Konfidenz + Trader-Läufe + KI-Entscheidungen |
| Aktien | Summary + Aktien-Verlauf + Depot-Trade-Historie + Ranking + Grid |
| ETF | Summary + ETF-Verlauf + Depot-Trade-Historie + Übersicht |
| Spekulation | Summary + Spec-Verlauf + Depot-Trade-Historie + Subtabs (Übersicht/Positionen/Watchlist) |

## 🔧 Bekannte Limits
- KI-Calls langsam (~8s/call) → Spec-Trader braucht ~6min
- ETF-Trader ohne KI (regelbasiert)
- OpenAI-Konto leer → nur Fallback-Provider genutzt

## 📚 Weitere Doku
- `docs/CHANGELOG.md` — Vollständige Versions-Historie
- `docs/ARCHITEKTUR.md` — System-Details
- `docs/ORDER-RISK-CHECKLIST.md` — 15-Check-Liste vor jeder Order (Order-Intent, v2.37.0)
- `docs/BROKER-CONNECTOR-SPECIFICATION.md` — BrokerProvider-Schnittstelle + Paper-Adapter (v2.37.0)
- `docs/PLATFORM-IMPLEMENTATION-REPORT.md` — Abschlussbericht Mandanten-Ausbauauftrag (v2.37.0)
- `PROJEKT-UEBERGABE-v2.8.4.md` — (veraltet, siehe CHANGELOG)

---
*Diese Doku wird bei jeder Versionierung aktualisiert. Letzter Stand: v2.43.0*
