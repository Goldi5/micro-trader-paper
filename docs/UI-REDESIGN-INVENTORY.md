# UI-REDESIGN-INVENTORY.md

> Bestandsaufnahme der aktuellen Micro-Trader-Oberfläche vor dem Redesign.
> Stand: 2026-08-09 · v2.43.0 · HEAD `101cd84`
> Auftrag: „Micro-Trader — vollständiges modernes Dashboard-Redesign" (Phase 0)

---

## 1. Geprüfte Dateien

| Datei | Größe | Inhalt |
|---|---|---|
| `dashboard.html` | 2742 Zeilen / 174 KB | Haupt-Dashboard (komplettes CSS inline + JS inline + HTML) |
| `dashboard.py` | 3261 Zeilen / 149 KB | Flask-Routen: Dashboard, /data-API, Admin (8 Seiten), Login, MFA, Setup-MFA, alle /api/*-Routen |
| `security.py` | 1881 Zeilen | Rollen/MFA/Sessions (nur geprüft, nicht Teil des UI) |

**Kein separates CSS/JS**: Alles lebt in einer einzigen HTML-Datei (Inline-CSS im
`<style>`-Block Z8–287 + 498 Inline-`style="…"`-Attribute im Body/JS-Templates).
Admin-CSS separat als Python-String `ADMIN_CSS` in dashboard.py (Z2216–2260).

---

## 2. Hauptnavigation (aktuell: 10 Pill-Tabs)

```html
<div class="tabs">  <!-- Z327–338 -->
  📊 Übersicht · 📈 Aktien · 📦 ETF · 🔥 Spekulation · 📊 Analyse ·
  🗃️ Analyse DB · 📰 News · 🤖 KI-Log · 📋 Log · ⚙️ Einstellungen
</div>
```

| Tab | Panel-ID | Inhalt (kurz) |
|---|---|---|
| Übersicht | `panel-overview` | Suche, 6 Stat-Karten (Gesamtwert, Rendite, G/V, akt. Aktien/ETF/Spec), Profil-Karten, Depot-Rows |
| Aktien | `panel-stocks` | Aktien-Tabelle + Charts je Ticker |
| ETF | `panel-etf` | ETF-Depots + Charts |
| Spekulation | `panel-spec` | Spec-Untertabs (Switch), Watchlist, Spec-Depots |
| Analyse | `panel-charts` | Chart-Panel (SVG-Liniencharts, Ticker-Detail) |
| Analyse DB | `panel-analyse2` | SQLite-Datenanalyse (DB-Karten, DB-Query) |
| News | `panel-news` | News-Feed (Karten mit Ticker-Topics, KI-Score) |
| KI-Log | `panel-ki` | 6 KI-Subtabs: Auswertung, Entscheidungen, News, Lernen, Regeln, „Was lernt die KI?" |
| Log | `panel-log` | System-Log |
| Einstellungen | `panel-settings` | Settings-Tabs (konto, benutzer, trading, …) |

---

## 3. Elemente-Bestandsaufnahme (mit Priorität P0–P3)

| Element | Aktuelle Position | Inhalt | Wichtigkeit | Ziel (§4–§8) | Priorität |
|---|---|---|---|---|---|
| **Gesamtwert** | Übersicht, Stat-Karte | KPI (nur Aktien-Total, ohne ETF/Spec im Wert) | sehr hoch | Hero-Bereich Startseite, großer Wert | **P0** |
| Gesamt-Rendite | Übersicht, Stat-Karte | % gesamt | sehr hoch | Hero (Gesamt-Rendite + Tagesänderung) | P0 |
| Gewinn/Verlust | Übersicht, Stat-Karte | abs. G/V | hoch | Hero (Sekundär) | P1 |
| aktive Aktien/ETF/Spec | Übersicht, 3 Stat-Karten | Zähler | mittel | KPI-Bereich (4 Karten: Aktien/ETF/Spec/System) | P1 |
| **Profil-Karten** (`profil-karten`) | Übersicht, unter Stats | Markt (z.B. US), Modus shadow/live, Gewinn, Positionen | hoch | KPI-Bereich + Modus-Anzeige im Header | P1 |
| **Risikodepots** (Aktien) | Übersicht, Depot-Rows | Depot je Risikostufe: Wert, Rendite, SL/TP/DD, Trades, Positionen, Regeln, Chart | hoch | Portfolios-Seite → Depot-Karten → Drawer | P1 |
| ETF-Depots | ETF-Tab | je Risikostufe: Wert, Rendite, Positionen, Chart | hoch | Portfolios (Unterbereich ETF) | P1 |
| Spec-Depots | Spekulation-Tab | Watchlist + Spec-Depots (Shares, WKN, Kaufpreis) | hoch | Portfolios (Unterbereich Spekulation) | P1 |
| Depot-Detail (`showDepot`) | Klick auf Depot → `panel-detail` | Fullscreen-Panel: Positionen, Trades, Chart, Regeln, KI-Decisions | sehr hoch | **Detail-Drawer (rechts, max 480px)** | P1 |
| Ticker-Chart (`showTickerChart`) | Klick auf Ticker | Chart + Info im Detail-Panel | hoch | Drawer (Ticker-Drawer) | P1 |
| News-Feed | News-Tab, Karten | Titel, Ticker-Topics, Alter, KI-Score | mittel | Aktivität (News als Feed, kompakt) | P1 |
| KI-Log (6 Subtabs) | KI-Tab | Auswertung, Entscheidungen (togglebar), News, Lernen, Regeln, Erklärung | mittel | KI-Seite (Übersicht + 4 Bereiche) | P1 |
| Analyse | Analyse-Tab | Charts, Ticker-Detail | mittel | Analyse (Performance, Drawdown, Benchmark) | P1 |
| Analyse DB | Analyse-DB-Tab | SQLite-Karten + Query | niedrig | Analyse (Datenqualität) / System | P2 |
| System-Log | Log-Tab | Zeilen-Log | niedrig | System | P2 |
| **Einstellungen** | Settings-Tab | Tabs: konto, benutzer, trading, lernen, provider, sicherheit, … | hoch | Einstellungen (eigener Bereich) | P1 |
| Konto (eigener Account) | Settings → konto | Profil, Passwort, MFA, Permissions, Tenant-Scope | hoch | Benutzer-Menü → Mein Konto | P1 |
| Benutzer-Verwaltung | Settings → benutzer | Liste, create, Rolle, deaktivieren, PW-Reset, Revoke | hoch | Admin (nicht Haupt-Tab!) | P1 |
| Tenant-Scope | Settings → konto (ausklappbar) | aktuelle Limits, Modi, Freigaben | hoch | Benutzer-Menü → Modus/Tenant | P1 |
| Suche (`searchTicker`) | Übersicht oben | Live-Tickersuche mit Dropdown | hoch | Globale Suche im Header | P0 |
| Pause-Trading-Button | Übersicht (Profil-Karten-Bereich) | Trading pausieren/fortsetzen | hoch | Hero rechts (nur mit Recht) | P1 |
| **Admin-Bereich** | eigener Tab `window.open('/admin')` | 8 Seiten: Übersicht, System, Benutzer, Mandanten, Logins, Sicherheit, Audit, Backups | hoch | Benutzer-Menü → Admin-Bereich (nicht Hauptnav) | P2 |
| Login | `/` (dashboard.py) | nackte HTML-Form (Browser-Default) | sehr hoch | **zentrale Login-Karte im Designsystem** | P0 |
| MFA-Verify | `/mfa` | nackte Form | sehr hoch | Login-Karte (2. Stufe) | P0 |
| Setup-MFA | `/setup_mfa` | nackte Form | hoch | Login-Karte / Konto | P0 |
| Landing | `/landing` | einfache Seite | niedrig | übernehmen/angleichen | P2 |

---

## 4. Subtabs & Unterseiten

| Bereich | Subtabs | Mechanismus |
|---|---|---|
| Spekulation | `switchSpecTab()` — mehrere Spec-Panes | JS-Switch, `spec-subtab`-Buttons |
| KI-Log | `kiSubTab()` — 6 Subpanels (`data-ki=`) | CSS-Klasse `ki-subpanel` + JS |
| Einstellungen | `switchSettingsTab()` — Tabs (konto, benutzer, …) | JS-generierte Tabs, `settings-tab-panel` |
| Spec-Watchlist | `filterSpecWatch()` / `sortSpecWatch()` | Filter-Pills + sortierbare Tabelle |
| KI-Entscheidungen | `toggleKiDec()` | Aufklappen/Details |

---

## 5. Modals & Overlays

| Element | Mechanismus | Bewertung |
|---|---|---|
| `riskModal()` (Z2101) | **`prompt()`-Dialoge** (Position-Size, SL, TP, DD) | ❌ Nicht redesign-fähig → echte Modal-Komponente in Phase 5 |
| `searchResults` | Dropdown unter Suchfeld | OK, in Header-Suche übernehmen |
| `userMenu` | Dropdown im Header (Konto, Einstellungen, Admin, Abmelden) | OK, in neue Navigation übernehmen |
| `msg()` | vermutlich Alert-ähnliche Meldung | prüfen |

---

## 6. Tabellen

Keine einzige `<table id="…">` — alle Tabellen werden **dynamisch per JS
gerendert** (innerHTML-Templates). Wichtigste:

| Tabelle | Rendering | Spalten |
|---|---|---|
| Aktien-Tabelle | `renderCard()`/`load()` | Ticker, Kurs, Rendite, Chart, … |
| Spec-Watchlist | `renderSpecTab()` | Ticker, Name, Kurs, Watch-Daten, sortierbar |
| KI-Entscheidungen | `toggleKiDec()` | Zeit, Ticker, Depot, Aktion, Begründung, Status |
| DB-Karten (analyse2) | `renderCard()` | Tabellen-Karten |
| Benutzerliste | `ladeBenutzerVerwaltung()` | Name, Rolle, Status, MFA, Aktionen |
| Audit/Logins (Admin) | Admin-HTML | Admin-seitig |

---

## 7. Charts

| Chart | Funktion | Typ |
|---|---|---|
| Depot-Charts (Übersicht) | `svgLineChart()` | SVG-Line (eigen, kein Chart.js) |
| Ticker-Charts | `tchart_${i}` / `histTable()` | SVG + Hist-Tabelle |
| Spec-Charts | `specChart_${t}` | SVG |
| Detail-Chart | `detChartCanvas` (canvas) | Canvas |

---

## 8. API-Aufrufe (aus dashboard.html)

| Aufruf | Zweck |
|---|---|
| `fetch('/api/profil_karten')` | Profil-Karten (Markt, Modus, Gewinn, Positionen) |
| `fetch('/api/profile?set=')` | Profil wechseln |
| `fetch('/api/pause_trading?state=')` | Trading pausieren/resume |
| `fetch('/api/report_list')` / `'/api/report_pdf'` | PDF-Reports |
| `/data` (hauptsächlich) | Gesamt-Datenpaket (Depots, ETF, Spec, News, KI, Log) |
| `/api/settings` GET/POST | Einstellungen |
| `/api/me`, `/api/me/password`, `/api/me/mfa` | Konto |
| `/api/users*` | Benutzerverwaltung |
| `/api/tenants*` | Tenant-Verwaltung |
| `/api/risk`, `/api/risk/set` | Risiko-Limits |
| `/api/approval*` | Freigaben |
| `/search_ticker`, `/ticker_chart`, `/depot_json`, `/spec_depot_json`, `/etf_depot_json`, `/api/analysis`, `/api/db_query`, `/api/db_karten`, `/api/version`, `/api/ki_log`, `/api/clear_cache` | Analyse/DB/KI |

---

## 9. Responsive & Layout

| Aspekt | Ist-Zustand | Ziel |
|---|---|---|
| Breakpoints | **nur 1**: `@media(max-width:700px)` für `.two-col` | Desktop 1440/1920 · Tablet 1024 · Mobile 768/390 |
| Grid | `.grid: repeat(auto-fill,minmax(230px,1fr))` | 12-Spalten-Hauptgrid (Chart 8 / Aktivität 4) |
| Navigation | horizontale Pill-Overflow (`overflow-x:auto`) | Top-Nav Desktop, scrollbar/Bottom mobile |
| max-width | keine feste Content-Breite (body-Padding 16–20px) | max 1440px zentriert |
| Zeilenumbruch | `.two-col` → 1fr unter 700px | Tablet 8 Spalten, Mobile 1 |

---

## 10. Inline-Styles (Problemquelle)

- **498×** `style="…"` direkt in HTML/JS-Templates → Design-Token-Refactoring nötig
- Beispiele: Header (Z288–322), Profil-Karten, alle JS-Renderfunktionen
- Risiko: Duplikation, keine zentrale Steuerbarkeit, Widersprüche zum Stylesheet

---

## 11. Accessibility (Ist-Zustand)

| Aspekt | Status |
|---|---|
| Fokus-Zustände | ❌ kaum sichtbare `:focus`-Styles (nur Suche) |
| aria-Labels | ❌ Icon-Buttons ohne aria-label (Emoji-Buttons) |
| Keyboard | teils (Tab-Navigation nativ), Drawer/Modal fehlen |
| Kontrast | ⚠️ `--text-dim:#64748b` auf Weiß = 4.6:1 (grenzwertig), 9px-Texte (`.pk-*`, `9.5px`) zu klein |
| prefers-reduced-motion | ❌ nicht vorhanden |
| Farb-allein-Information | ⚠️ Status teils nur Farbe (positiv/negativ) |

---

## 12. Risiken & Abweichungen

1. **498 Inline-Styles** → größtes Refactoring-Risiko, Token-Umstellung nötig.
2. `riskModal()` nutzt `prompt()` → muss durch echte Modal ersetzt werden (Phase 5).
3. **Gesamtwert-KPI zählt nur Aktien** (kein ETF/Spec-Gesamtwert im Hero) → Phase 4 klären, ob /data das liefert.
4. Admin-CSS ist ein separater Python-String → Design-Tokens müssen für Admin und Dashboard **eine** Quelle haben.
5. Login/MFA/Setup-MFA sind nackte HTML → komplette Neuverkleidung, Sicherheitslogik unangetastet.
6. 10 gleichwertige Tabs → Reduktion auf 8 Bereiche (§5 Auftrag).
7. Nur 1 Breakpoint → vollständiges Responsive-Konzept nötig (§14 Auftrag).
8. `/data` lädt vermutlich alles auf einmal (große JSON-Pakete) → Performance-Prüfung Phase 13.

---

*Phase 0 Bestandsaufnahme · 2026-08-09*
