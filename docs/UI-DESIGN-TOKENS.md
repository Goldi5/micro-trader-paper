# UI-DESIGN-TOKENS.md

> Design-Token-Definition für das Micro-Trader-Redesign — „Calm Trading Command Center".
> Stand: 2026-08-09 · Auftrag §6 „Phase 2 — Designsystem"
> Stil: moderner Fintech-Control-Center-Stil — ruhig, präzise, hochwertig, klar.
> Weniger Glas, weniger Blur, weniger Badges/Schatten → klare Flächen, Border statt Schatten.

---

## 1. Farben (CSS-Variablen — verbindlich)

```css
/* Basis */
--bg: #f7f9fc;            /* Seitenhintergrund: fast weiß, leicht kühl */
--surface: #ffffff;       /* Karten/Flächen: opak weiß */
--surface-muted: #f1f4f8; /* abgesetzte Flächen (Hover, Alternating) */
--border: #e5eaf0;        /* Border statt Schatten */
--text: #0f172a;          /* Primärtext (Slate 900) */
--text-secondary: #64748b;/* Sekundärtext */
--text-muted: #94a3b8;    /* Tertiärtext/Labels */

/* Primär (elektrisches Blau) */
--primary: #2563eb;
--primary-dark: #1d4ed8;
--primary-soft: #eff6ff;  /* aktive Nav-Hintergründe, Badges */

/* Status — nur für Bedeutung */
--success: #059669;       /* Gewinne, gesund */
--success-soft: #ecfdf5;
--warning: #d97706;       /* Warnungen */
--warning-soft: #fffbeb;
--danger: #dc2626;        /* Verluste, Fehler */
--danger-soft: #fef2f2;
--purple: #7c3aed;        /* KI/analytisch */
--purple-soft: #f5f3ff;
```

**Regeln:**
- Grün/Rot NUR für Gewinn/Verlust/Warnung — nie dekorativ.
- Keine Verläufe ohne Informationsfunktion.
- Badges nur mit Soft-Hintergrund (`*-soft`) + kräftiger Textfarbe derselben Familie.

---

## 2. Radien

```css
--radius-sm: 8px;   /* Buttons, Inputs, kleine Elemente */
--radius-md: 12px;  /* Karten */
--radius-lg: 16px;  /* große Container, Drawer, Modals */
--radius-pill: 999px; /* Pills, Chips, Modus-Badges */
```

---

## 3. Typografie

```css
font-family: "Inter", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif;
```

> Keine externe Schrift erzwingen — Fallback auf `Segoe UI Variable` (bereits im System).

### Hierarchie (verbindlich)

| Stufe | Größe | Gewicht | Verwendung |
|---|---|---|---|
| Hero-Wert | **40–48px** | 700 | Portfolio-Gesamtwert Startseite |
| Seitentitel | **24–28px** | 700 | Überschrift je Bereich |
| Bereichstitel | **16–18px** | 600–700 | Panel-Header, Drawer-Titel |
| KPI-Wert | **22–28px** | 700 | KPI-Karten (Aktien/ETF/Spec/System) |
| Text | **13–14px** | 400 | Standardtext |
| Sekundärtext | **12px** | 400 | Meta, Beschreibungen |
| Labels | **11px** | 500–600 | Uppercase-Labels, Tabellen-Header |

**Verboten:** 9px-Texte für wichtige Informationen (aktuell `.pk-*` 9.5px,
`.src` 9.5px → auf ≥11px anheben).

```css
font-variant-numeric: tabular-nums;  /* Zahlen tabellarisch (bleibt) */
```

---

## 4. Oberflächen & Schatten

```css
--shadow-sm: 0 1px 2px rgba(15,23,42,.04);
--shadow-md: 0 4px 12px rgba(15,23,42,.08);  /* NUR Dropdowns, Drawer, Dialoge, Modals */
--shadow-lg: 0 12px 32px rgba(15,23,42,.12); /* Drawer/Modal-Overlays */
```

**Regeln:**
- Karten: `--surface` + `border: 1px solid var(--border)` — **kein** Schatten.
- Schatten nur für: Dropdowns, Drawer, Dialoge, Modals, Sticky-Header (dezent).
- Kein Schatten auf jedem KPI.
- Blur (`backdrop-filter`) NUR im Header und Overlays — nicht auf Karten.

---

## 5. Layout-Raster

```css
--container-max: 1440px;  /* maximale Inhaltsbreite, zentriert */
--grid-12: 12 columns;    /* Desktop: Chart 8 / Aktivität 4 */
--grid-8: 8 columns;      /* Tablet */
--grid-1: 1 column;       /* Mobile */
--gap: 16px;              /* Basis-Abstand */
--space-hero: 32px;       /* Hero-Bereich */
```

| Breakpoint | Verhalten |
|---|---|
| ≥1200px (Desktop) | 12-Spalten, Chart 8 / Aktivität 4, KPI 4-spaltig |
| 768–1199px (Tablet) | 8 Spalten, Aktivität unter Chart, KPI 2-spaltig |
| <768px (Mobile) | 1 Spalte, KPI horizontal scrollbar/untereinander, Drawer volle Breite |

---

## 6. Komponenten-Spezifikation (Ziel)

### Header
- `--surface` mit dezentem `--shadow-sm` + `border-bottom: 1px solid var(--border)`
- dunkler, kompakter Header (Auftrag: „ein dunkler, kompakter Header") — **dunkle Fläche** `#0f172a`-Variante mit hellem Text (siehe Zielanordnung), Logo links, Nav mittig, Suche + User rechts
- Modus-Pill (SHADOW/PAPER) mit `--radius-pill` + Statusfarbe (amber/green)

### Hero-Karte (Startseite)
- Große Fläche, KEINE Glas-Karte: `--surface`, `--radius-lg`, 1px Border
- Links: Label „PORTFOLIO" (11px uppercase), Gesamtwert 44px/700, Rendite-Zeile (+grün/−rot), Stand-Zeitpunkt
- Rechts: Modus-Badge, Marktstatus, Systemstatus, [Trading pausieren]-Button (nur mit Recht)

### KPI-Karten (max 4)
- `--surface`, `--radius-md`, 1px Border, Padding 16–20px
- Wert 24px/700 · Rendite 13px (±Farbe) · Label 11px uppercase · Klickziel (Portfolios)

### Tabellen
- Sticky Header (11px uppercase `--text-secondary`), Zeilen 13px
- Zeilen-Hover `--surface-muted`, Border-bottom `--border`
- Sortierbare Spalten mit Pfeil, Filter, Suche, Pagination
- Leer-/Lade-/Fehlerzustände mit Text (kein nacktes „Keine Daten")

### Drawer (Phase 5)
- Rechts, **max 480px** Desktop / volle Breite Mobile
- `--surface`, `--radius-lg` (links abgerundet), `--shadow-lg`, Overlay `rgba(15,23,42,.4)`
- Escape schließt, Fokus-Trap, Header mit Titel + X
- Sektionen als Accordion/Untertabs

### Modal (ersetzt prompt()-Dialoge)
- Zentriert, `--radius-lg`, `--shadow-lg`, Overlay
- Header, Body, Footer-Aktionen (Primär/Sekundär/Danger)

### Buttons
- Primär: `--primary` BG, weißer Text, `--radius-sm`, Hover `--primary-dark`
- Sekundär: transparent, 1px `--border`, Text `--text`
- Danger: `--danger-soft` BG, `--danger` Text
- Ghost: nur Text

### Login/MFA (Phase 10)
- Zentrale schmale Karte (max ~400px): Logo, Titel, Inputs, Fehler inline
- MFA als eigene Stufe (2-Step)
- **Sicherheitslogik unverändert** — nur Verkleidung

---

## 7. Migration von Alt → Neu (Token-Mapping)

| Alt (altes Design) | Neu |
|---|---|
| `--bg1/#f8fafc, --bg2/#f1f5f9` | `--bg: #f7f9fc` |
| `--card-bg: rgba(255,255,255,.78)` + blur | `--surface: #ffffff` (opak) |
| `--card-border: rgba(15,23,42,.07)` | `--border: #e5eaf0` |
| `--accent: #2563eb` | `--primary: #2563eb` |
| `--green: #10b981` | `--success: #059669` |
| `--amber: #f59e0b` | `--warning: #d97706` |
| `--red: #ef4444` | `--danger: #dc2626` |
| `--purple: #8b5cf6` | `--purple: #7c3aed` |
| `--radius: 14px / --r-lg: 18px / --r-sm: 10px` | `--radius-sm/md/lg: 8/12/16px` |
| `--shadow: 0 10px 28px …` (überall) | `--shadow-sm/md/lg` (nur Overlays) |
| 9.5–10px Texte | ≥11px |
| `--glass-strong`, `--edge`, `--edge2` | entfallen (kein Glas mehr) |

> Ziel: **eine** Token-Quelle für Dashboard UND Admin (ADMIN_CSS wird auf dieselben
> Variablen umgestellt oder erbt von einer gemeinsamen `:root`).

---

*Phase 2 Designsystem · 2026-08-09*
