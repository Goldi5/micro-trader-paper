# UI-INFORMATION-ARCHITECTURE.md

> Neue Informationsarchitektur für das Micro-Trader-Dashboard-Redesign.
> Stand: 2026-08-09 · Auftrag §5 „Phase 1 — Informationsarchitektur"
> Prinzip: **Die wichtigste Information ist sofort sichtbar, alles Weitere ist genau einen Klick entfernt.**

---

## 1. Hauptnavigation (maximal 8 Bereiche)

```text
[Logo] Micro-Trader
[Übersicht] [Portfolios] [Märkte] [Analyse] [Aktivität] [KI] [System]
                                          [Suche] [Benutzer▾]
```

| # | Bereich | Inhalt | Alte Tabs → Ziel |
|---|---|---|---|
| 1 | **Übersicht** | Gesamtportfolio, Rendite, Marktstatus, Tradingmodus, Risiko, wichtigste Warnungen, letzte Aktivitäten | `overview` |
| 2 | **Portfolios** | Aktien, ETF, Spekulation als Unterbereiche; Depot-Karten, Positionen, Risikostufen | `stocks` + `etf` + `spec` (zusammengeführt!) |
| 3 | **Märkte** | Watchlist, Marktstatus, Kurse, News, Providerstatus, Börsenstatus | `spec-watchlist`-Anteil + `news` |
| 4 | **Analyse** | Performance, Drawdown, Benchmark, Trefferquote, Regelwirkung, Datenqualität | `charts` + `analyse2` |
| 5 | **Aktivität** | Trades, KI-Entscheidungen, News, Systemereignisse, Audit | `news` + `log` + KI-Entscheidungen |
| 6 | **KI** | Entscheidungen, Lernfortschritt, aktive Regeln, Shadow-Regeln, Regelkonflikte, Regelversion | `ki` (6 Subtabs) |
| 7 | **System** | Engine, Cron, Provider, Datenqualität, Gesundheit, Fehler, Audit-Zusammenfassung, „Über das System" (Version) | `log` + Admin-System-Anteile |
| 8 | **Einstellungen** | persönliche, Trading-, Lern-Einstellungen, Provider, Sicherheit, Benutzer, Admin (wenn berechtigt) | `settings` |

**Admin erscheint NICHT als Haupttab** → im Benutzer-Menü (nur für Admins sichtbar).

---

## 2. Startseite (Übersicht) — Ziel-Layout

```text
┌──────────────────────────────────────────────────────────────┐
│ Header: Logo · Übersicht Portfolios Märkte Analyse Aktivität KI System │ Suche User▾ │
│         Tenant/Workspace · Modus-Pill · Marktstatus · Uhrzeit            │
├──────────────────────────────────────────────────────────────┤
│ HERO:  PORTFOLIO                              PAPER · MARKT OFFEN │
│        10.842,60 €                            System stabil       │
│        +4,82 % gesamt  +0,73 % heute         [Trading pausieren] │
│        Stand vor 2 Min.                                          │
├──────────────────────────────────────────────────────────────┤
│ KPI:   Aktien  |  ETF  |  Spekulation  |  System               │
│        4.212 €    3.881 €    2.749 €        stabil             │
│        +3,2 %     +2,1 %     +8,7 %        273 Tests           │
├──────────────────────────────────────────────────────────────┤
│ 8 Spalten → Portfolio-Verlauf (Chart)   4 Spalten → Aktivität  │
│        1T · 1W · 1M · 3M · Gesamt        Timeline (max 5)      │
├──────────────────────────────────────────────────────────────┤
│ Risiko-Übersicht (kompakt)               KI-/Systemstatus      │
│ Drawdown · Exposure · Sperren · Limits    Regelversion · Provider · Datenqualität │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Bereichs-Zuordnung (Element → neuer Ort)

| Element (alt) | Neuer Ort | Klickpfad |
|---|---|---|
| Gesamtwert-KPI | Übersicht → Hero | 0 Klicks |
| Gesamt-Rendite / Tagesänderung | Übersicht → Hero | 0 Klicks |
| Profil-Karten (Markt/Modus) | Übersicht → Hero rechts + Header-Pill | 0 Klicks |
| Risikodepots Aktien | Portfolios → Karten | 1 Klick (Tab) |
| ETF-Depots | Portfolios → Unterbereich ETF | 1 Klick |
| Spec-Depots | Portfolios → Unterbereich Spekulation | 1 Klick |
| Depot-Detail (Positionen, Trades, Regeln, KI) | Portfolios → **Drawer** | 2 Klicks |
| Ticker-Chart | Märkte / überall → **Drawer** | 2 Klicks |
| Watchlist | Märkte → Watchlist | 1 Klick |
| News | Aktivität (Feed) + Märkte (Kurse/News) | 1 Klick |
| KI-Entscheidungen | KI → Entscheidungen | 1 Klick |
| KI-Auswertung (Stats) | KI → Übersicht | 0 Klicks (innerhalb KI) |
| KI-Regeln | KI → Regeln (Filter Aktiv/Shadow/Archiv) | 1 Klick |
| KI-Lernen | KI → Lernfortschritt | 1 Klick |
| Analyse-Charts | Analyse → Performance/Drawdown | 1 Klick |
| Analyse-DB (SQLite) | Analyse → Datenqualität / System | 2 Klicks |
| System-Log | System → Log | 1 Klick |
| Engine/Cron/Provider-Status | System → Übersicht | 0 Klicks (innerhalb System) |
| Version/Technik | System → Über das System | 2 Klicks |
| Einstellungen (Trading/Lernen/Provider) | Einstellungen | 1 Klick |
| Konto (Profil, PW, MFA, Permissions) | Benutzer-Menü → Mein Konto | 1 Klick |
| Tenant-Scope / Modus | Benutzer-Menü → Modus / Tenant | 1 Klick |
| Benutzer-Verwaltung | Einstellungen → Benutzer (Admin) | 2 Klicks |
| Admin-Bereich (8 Seiten) | Benutzer-Menü → Admin (nur Admin) | 1 Klick |
| Login / MFA / Setup-MFA | eigene zentrale Karten | — |

---

## 4. Portfolios-Struktur (Unterbereiche statt 3 Haupt-Tabs)

```text
Portfolios
├── Alle Portfolios (Gesamtwert, Rendite, Drawdown, offene Positionen, aktiver Modus)
├── Filter: Alle | Aktien | ETF | Spekulation  ·  Alle Modi | Shadow | Paper  ·  Alle Risiken
├── Portfolio-Karten (max 6 sichtbar)
│     Name · Modus · Wert · Rendite · Risiko · Positionen · Status
└── Klick → Drawer (max 480px):
      Zusammenfassung · Positionen · Cash · Chart · Trades · Regeln · KI-Entscheidungen
      · Risiko · Modus/Freigabe — als Accordion/Untertabs
```

---

## 5. KI-Struktur (Übersicht statt 6 gleichwertige Subtabs)

```text
KI
├── Übersicht: Anzahl Entscheidungen, Trefferquote, Lerneffekt, Regelversion,
│              unbestätigte Regeln, Regelkonflikte, Providerstatus
├── Entscheidungen (Tabelle, Zeile → Drawer)
├── Lernfortschritt
├── Regeln: Filter Aktiv | Shadow | Archiv
│           Karte: Regeltext, Status, Gewicht, Evidenz, letzte Bestätigung, Konfliktstatus
│           → Details im Drawer
└── Qualität
```

---

## 6. Aktivität-Struktur

```text
Aktivität
├── Trades (Zeit, Ticker, Aktion, Wert, Status)
├── KI-Entscheidungen
├── News (Priorität, Ticker, Score, Alter, Quelle, Titel — kompakter Feed)
├── Systemereignisse
└── Audit-Aktivität
```

---

## 7. System-Struktur

```text
System
├── Übersicht: Engine, Cron-Jobs, Provider-Status, Datenqualität, Gesundheit, Fehler
├── Log
├── Audit-Zusammenfassung
└── Über das System (Version, Build, technische Details — Version-Badge wandert hierher)
```

---

## 8. Prioritäts-Matrix (P0–P3)

| Stufe | Elemente |
|---|---|
| **P0** — sofort sichtbar | Gesamtwert, Gesamt-Rendite, Tagesänderung, Modus-Pill, Marktstatus, Suche, 4 KPI-Karten |
| **P1** — ein Klick | Portfolios, Märkte, Aktivität, KI-Übersicht, Depot-Karten, News-Feed, Einstellungen, Mein Konto |
| **P2** — Detailansicht | Depot-Drawer, Ticker-Drawer, KI-Regel-Drawer, Analyse-DB, System-Log, Admin-Bereich |
| **P3** — Admin/Technik | Audit-Rohdaten, Backups, Tenants-Admin, Benutzer-Verwaltung |

---

## 9. Was entfällt / sich ändert

1. **10 Pill-Tabs → 8 Top-Nav-Items** (Übersicht, Portfolios, Märkte, Analyse, Aktivität, KI, System, Einstellungen).
2. Aktien/ETF/Spekulation werden **Unterbereiche von Portfolios** (keine 3 gleichrangigen Hauptseiten).
3. News wandert von Haupt-Tab in **Aktivität** (Feed) und **Märkte**.
4. Log + Analyse-DB verlieren Haupt-Tab-Status → **System** bzw. **Analyse**.
5. Version-Badge aus Header → **System → Über das System**.
6. Admin nicht mehr als eigener Tab → **Benutzer-Menü** (rollenbasiert).
7. Depot-Details nicht mehr Fullscreen-Panel → **Drawer**.
8. `riskModal()`-prompts → **echtes Modal**.

---

*Phase 1 Informationsarchitektur · 2026-08-09*
