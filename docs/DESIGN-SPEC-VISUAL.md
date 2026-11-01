# Micro-Trader — Visuelle Design-Spezifikation (für KI-Review)

> **Zweck:** Vollständige, wörtliche Beschreibung des visuellen Erscheinungsbilds
> der Micro-Trader-Oberflächen, damit eine andere KI das Design ohne Zugriff auf
> die Dateien exakt nachvollziehen und prüfen kann.
> **Quellen:** `dashboard.html` (Haupt-Dashboard), `dashboard.py` (Admin-Bereich,
> Login/MFA-Views). Extrahiert am 2026-08-09, Stand v2.43.0.
> **Hinweis:** Alle CSS-Blöcke sind 1:1 aus dem Code kopiert (nicht paraphrasiert).

---

## 0. Übersicht der Oberflächen

| Oberfläche | Route | Datei/Quelle | Styling |
|---|---|---|---|
| Haupt-Dashboard | `/dashboard` | `dashboard.html` (2742 Zeilen) | Komplettes CSS im `<style>`-Block (Z8–287) |
| Admin-Bereich (8 Unterseiten) | `/admin`, `/admin/system`, `/admin/users`, `/admin/tenant-config`, `/admin/logins`, `/admin/security`, `/admin/audit`, `/admin/backups` | `dashboard.py`, `ADMIN_CSS` (Z2216–2260) | Eigenes CSS, „StufenPilot-Design" |
| Login | `/login` | `dashboard.py` `def login()` (Z2025–2056) | **Kein Custom-CSS** — nackte HTML-Form (inline) |
| MFA-Verify | `/mfa` | `dashboard.py` Z2071–2088 | **Kein Custom-CSS** — nackte HTML-Form |
| Setup-MFA | `/setup_mfa` | `dashboard.py` Z2091+ | **Kein Custom-CSS** |

**Wichtig für Review:** Login/MFA sind bewusst OHNE Styling (Basis-HTML), das
Dashboard und der Admin-Bereich haben komplett separate CSS-Systeme.

---

## 1. Haupt-Dashboard (`dashboard.html`)

### 1.1 Dokumentkopf

```html
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>📊 Micro-Trader</title>
```

### 1.2 CSS-Variablen (Design-Tokens)

```css
:root {
  --bg1: #f8fafc;
  --bg2: #f1f5f9;
  --bg: #f8fafc;
  --card-bg: rgba(255,255,255,0.78);
  --card-border: rgba(15,23,42,0.07);
  --card-hover: rgba(255,255,255,0.97);
  --glass-strong: rgba(255,255,255,0.94);
  --edge: rgba(255,255,255,0.92);
  --edge2: rgba(15,23,42,0.07);
  --accent: #2563eb;
  --accent-soft: #eff6ff;
  --accent-dark: #1d4ed8;
  --green: #10b981;
  --amber: #f59e0b;
  --red: #ef4444;
  --purple: #8b5cf6;
  --text: #0f172a;
  --text-dim: #64748b;
  --text2: #64748b;
  --text3: #94a3b8;
  --radius: 14px;
  --r-lg: 18px;
  --r-sm: 10px;
  --shadow: 0 10px 28px rgba(15,23,42,.08);
  --shadow-lg: 0 24px 48px rgba(61,93,153,.12);
}
```

**Farbfamilie:** Slate-Blau-Palette (wie StufenPilot): Akzent `#2563eb`,
Text `#0f172a`, dim `#64748b`, Erfolg `#10b981` (grün), Warnung `#f59e0b`
(amber), Fehler `#ef4444` (rot), Violett `#8b5cf6`.

### 1.3 Basis-Reset + Body

```css
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:'Segoe UI Variable','Segoe UI',system-ui,-apple-system,sans-serif;
  -webkit-font-smoothing:antialiased;
  background:linear-gradient(160deg,var(--bg1),var(--bg2));
  background-image:
    radial-gradient(ellipse at 15% 0%, rgba(10,132,255,0.08) 0%, transparent 55%),
    radial-gradient(ellipse at 85% 0%, rgba(48,209,88,0.06) 0%, transparent 50%);
  background-attachment:fixed;
  color:var(--text);
  padding:16px 20px;
  min-height:100vh;
  font-variant-numeric:tabular-nums;
}
.num,td,th{font-variant-numeric:tabular-nums}
h1{font-size:27px;font-weight:700;letter-spacing:-0.5px;margin-bottom:6px;cursor:pointer;display:flex;align-items:center;gap:6px}
h1 span{font-size:12px;font-weight:400;color:var(--text-dim)}
```

**Font-Stack (global):** `'Segoe UI Variable','Segoe UI',system-ui,-apple-system,sans-serif`
— Tabellenzahlen mit `tabular-nums` (Spalten ruhig).

### 1.4 Tabs (Navigation)

```css
.tabs{display:flex;gap:3px;margin-bottom:8px;background:rgba(118,118,128,.10);padding:3px;border-radius:999px;overflow-x:auto;scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{padding:4px 11px;cursor:pointer;font-size:11.5px;font-weight:500;color:var(--text-dim);background:transparent;border:none;border-radius:999px;transition:all .18s cubic-bezier(.32,.72,0,1);white-space:nowrap}
.tab:hover{color:var(--text)}
.tab.active{color:var(--text);background:#fff;box-shadow:0 1px 4px rgba(0,0,0,0.1)}
```

**Pillen-Tabs:** 10 Tabs — 📊 Übersicht, 📈 Aktien, 📦 ETF, 🔥 Spekulation,
📊 Analyse, 🗃️ Analyse DB, 📰 News, 🤖 KI-Log, 📋 Log, ⚙️ Einstellungen.
Aktiver Tab = weißes Pill auf grauem Track.

### 1.5 Panels

```css
.panel{display:none;animation:fadeIn 0.25s ease}
.panel.active{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px) scale(.99)}to{opacity:1;transform:translateY(0) scale(1)}}
```

Panels: `#panel-overview` (active), `#panel-stocks`, `#panel-etf`, `#panel-charts`,
`#panel-analyse`, `#panel-analyse2`, `#panel-news`, `#panel-ki`, `#panel-log`,
`#panel-spec`, `#panel-detail`, `#panel-settings`.

### 1.6 Suche

```css
.search-box{position:relative;margin-bottom:12px}
.search-box input{width:100%;padding:9px 14px;border:1px solid var(--card-border);border-radius:10px;font-size:13px;font-family:inherit;background:var(--card-bg);backdrop-filter:blur(20px);outline:none;transition:0.2s}
.search-box input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(59,130,246,0.15)}
.search-results{position:absolute;top:100%;left:0;right:0;z-index:100;background:#fff;border:1px solid var(--card-border);border-radius:10px;box-shadow:0 4px 20px rgba(0,0,0,0.1);max-height:300px;overflow-y:auto;display:none}
.search-results.active{display:block}
.search-results .sr-item{padding:8px 12px;cursor:pointer;border-bottom:1px solid rgba(0,0,0,0.05);font-size:12px}
.search-results .sr-item:last-child{border:none}
.search-results .sr-item:hover{background:rgba(59,130,246,0.04)}
.rank-nr{font-weight:600;width:28px}
.rank-nr.top3{color:var(--green)}
.ranking-tbl td,.ranking-tbl th{padding:5px 10px}
```

### 1.7 Spec-Untertabs + Filter-Pills

```css
.spec-subtabs{border-bottom:1px solid rgba(0,0,0,0.06);padding-bottom:0}
.spec-subtab{padding:7px 16px;cursor:pointer;font-size:12px;font-weight:500;color:var(--text-dim);background:transparent;border:none;border-radius:8px 8px 0 0;transition:all 0.2s}
.spec-subtab:hover{color:var(--text);background:rgba(0,0,0,0.03)}
.spec-subtab.active{color:var(--accent);background:rgba(59,130,246,0.08)}
.spec-pane{display:none;animation:fadeIn 0.2s ease}
.spec-pane.active{display:block}
.spec-filter{padding:4px 10px;cursor:pointer;font-size:11px;font-weight:500;border-radius:20px;border:1px solid var(--card-border);background:transparent;color:var(--text-dim);transition:all 0.2s}
.spec-filter:hover{color:var(--text);background:rgba(0,0,0,0.03)}
.spec-filter.active{color:var(--accent);background:rgba(59,130,246,0.1);border-color:var(--accent)}
.spec-watch-tbl{width:100%;border-collapse:collapse;font-size:12px}
.spec-watch-tbl th{padding:7px 8px;text-align:left;font-weight:500;color:var(--text-dim);font-size:11px;border-bottom:1px solid rgba(0,0,0,0.06);white-space:nowrap;user-select:none}
.spec-watch-tbl th.sortable{cursor:pointer}
.spec-watch-tbl th.sortable:hover{color:var(--accent)}
.spec-watch-tbl td{padding:4px 6px;border-bottom:1px solid rgba(0,0,0,0.03)}
.spec-watch-tbl tbody tr:hover{background:rgba(59,130,246,0.03)}
.spec-row.hidden{display:none}
```

### 1.8 Glassmorphismus-Karten (Kern-Design)

```css
.glass{
  background:var(--card-bg);
  backdrop-filter:blur(24px) saturate(180%);
  -webkit-backdrop-filter:blur(24px) saturate(180%);
  border:1px solid var(--edge);
  border-radius:var(--radius);
  padding:14px;
  margin-bottom:12px;
  transition:all .18s cubic-bezier(.32,.72,0,1);
  box-shadow:var(--shadow), inset 0 1px 0 rgba(255,255,255,.7);
  position:relative;
}
.glass::after{content:'';position:absolute;inset:0;border-radius:var(--radius);border-bottom:1px solid var(--edge2);border-right:1px solid var(--edge2);pointer-events:none}
.glass:hover{border-color:rgba(255,255,255,.9);transform:translateY(-1px);box-shadow:var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,.7)}
```

**Glas-Effekt:** weiß transluzent (78%), `blur(24px) saturate(180%)`, weicher
Schatten `0 10px 28px`, Hover hebt um 1px an mit größerem Schatten
`0 24px 48px rgba(61,93,153,.12)`.

### 1.9 Grid + Cards

```css
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}
.card{
  background:var(--card-bg);
  backdrop-filter:blur(10px) saturate(1.3);
  -webkit-backdrop-filter:blur(10px) saturate(1.3);
  border:1px solid var(--card-border);
  border-radius:var(--radius);
  padding:13px;
  cursor:pointer;
  transition:all 0.2s;
  box-shadow:var(--shadow);
}
.card:hover{
  border-color:rgba(0,0,0,0.1);
  transform:translateY(-1px);
  box-shadow:0 2px 8px rgba(0,0,0,0.06), 0 4px 20px rgba(0,0,0,0.04);
}
.card.positive{border-left:3px solid var(--green)}
.card.negative{border-left:3px solid var(--red)}
.card.neutral{border-left:3px solid rgba(0,0,0,0.08)}
.card h3{font-size:12px;font-weight:500;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:2px}
.card .wert{font-size:20px;font-weight:700;letter-spacing:-0.5px;color:var(--text)}
.card .rendite{font-size:13px;font-weight:500;margin-top:1px}
.card .meta{font-size:11px;color:var(--text-dim);margin-top:4px}
.positiv{color:var(--green)}.negativ{color:var(--red)}
```

### 1.10 Sector-Badges (Branchen-Farbcode)

```css
.badge{display:inline-block;font-size:9px;font-weight:600;padding:1px 6px;border-radius:4px;margin:1px 2px 0 0;letter-spacing:0.2px;white-space:nowrap}
.badge-tech{background:#dbeafe;color:#2563eb}
.badge-healthcare{background:#dcfce7;color:#16a34a}
.badge-finance{background:#fef3c7;color:#d97706}
.badge-energy{background:#fed7aa;color:#c2410c}
.badge-utilities{background:#e0e7ff;color:#4f46e5}
.badge-realestate{background:#f3e8ff;color:#7c3aed}
.badge-consumer-defensive{background:#fce7f3;color:#db2777}
.badge-consumer-cyclical{background:#fff7ed;color:#ea580c}
.badge-industrials{background:#e0f2fe;color:#0284c7}
.badge-basic-materials{background:#f0fdf4;color:#65a30d}
.badge-communication{background:#f0abfc;color:#a21caf}
.badge-technology{background:#dbeafe;color:#2563eb}
.badge-biotech{background:#ccfbf1;color:#0d9488}
.badge-crypto{background:#fef08a;color:#a16207}
.badge-meme{background:#fecaca;color:#dc2626}
.badge-inverse{background:#e5e5e5;color:#525252}
.badge-lev-bull{background:#bbf7d0;color:#15803d}
.badge-lev-bear{background:#fecaca;color:#b91c1c}
.badge-volatility{background:#ffedd5;color:#c2410c}
.badge-commodity{background:#fef3c7;color:#a16207}
.badge-ai{background:#e0e7ff;color:#4338ca}
.badge-ev{background:#d1fae5;color:#047857}
.badge-space{background:#e0f2fe;color:#0369a1}
```

**Muster:** Badge = sehr heller Pastell-Hintergrund (z. B. `#dbeafe` = helles
Blau) + kräftige dunkle Textfarbe derselben Farbfamilie (z. B. `#2563eb`).

### 1.11 Tabellen

```css
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;font-weight:500;color:var(--text-dim);padding:6px 8px;border-bottom:1px solid rgba(0,0,0,0.06);white-space:nowrap;font-size:11px;text-transform:uppercase;letter-spacing:0.5px}
td{padding:6px 8px;border-bottom:1px solid rgba(0,0,0,0.03)}
tr:hover td{background:rgba(0,0,0,0.02)}
```

### 1.12 Statistik-Leiste

```css
.summary-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.stat{
  background:var(--card-bg);
  backdrop-filter:blur(10px) saturate(1.3);
  -webkit-backdrop-filter:blur(10px) saturate(1.3);
  border:1px solid var(--card-border);
  border-radius:var(--radius);
  padding:10px 18px;
  text-align:center;
  min-width:85px;
  box-shadow:var(--shadow);
}
.stat .num{font-size:22px;font-weight:700;letter-spacing:-0.4px;color:var(--text)}
.stat .lbl{font-size:10.5px;font-weight:500;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px;margin-top:1px}
```

### 1.13 Zwei-Spalten-Layout (responsiv)

```css
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:700px){.two-col{grid-template-columns:1fr}}
```

### 1.14 Mover / News / KI-Log

```css
.mover{padding:2px 0;font-size:12px;display:flex;justify-content:space-between}
.mover .tik{font-weight:600}
.mover .chg{font-weight:500}
.news-list{max-height:500px;overflow-y:auto;display:flex;flex-direction:column;gap:5px}
.news-item{
  background:var(--card-bg);
  backdrop-filter:blur(10px) saturate(1.3);
  border:1px solid var(--card-border);
  border-radius:var(--radius);
  padding:9px 12px;
  font-size:12.5px;
  box-shadow:var(--shadow);
}
.news-item .title{color:var(--text)}
.news-item .topics{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}
.news-item .topic{background:rgba(59,130,246,0.08);color:var(--accent);padding:1px 7px;border-radius:10px;font-size:10px}
.news-item .age-new{color:#16a34a;font-size:10px;font-weight:600}
.news-item .age-now{color:#2563eb;font-size:10px;font-weight:500}
.news-item .age-old{color:var(--text-dim);font-size:10px}
.news-item .ki-score{color:var(--text-dim);letter-spacing:-1px}
.ki-table{width:100%;border-collapse:collapse;font-size:11.5px}
.ki-table th{text-align:left;padding:5px 8px;color:var(--text-dim);font-weight:500;border-bottom:1px solid var(--card-border)}
.ki-table td{padding:5px 8px;border-bottom:1px solid var(--card-border)}
.ki-table tr:hover{background:rgba(59,130,246,0.04)}
.ki-table .title-col{max-width:350px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ki-score-badge{background:rgba(59,130,246,0.08);padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600}
```

### 1.15 Buttons / Back / Detail-Header

```css
.back-btn{
  background:var(--card-bg);
  backdrop-filter:blur(10px);
  border:1px solid var(--card-border);
  color:var(--text);
  padding:7px 16px;
  border-radius:8px;
  cursor:pointer;
  font-size:12.5px;
  font-family:inherit;
  transition:all 0.15s;
  margin-bottom:10px;
  display:inline-block;
  box-shadow:var(--shadow);
}
.back-btn:hover{background:rgba(255,255,255,0.95);border-color:rgba(0,0,0,0.12)}
.detail-header{margin-bottom:10px}
.detail-header h2{font-size:16px;font-weight:600}
.detail-header .sub{font-size:12px;color:var(--text-dim);margin-top:2px}
```

### 1.16 Scrollbar + Charts

```css
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(0,0,0,0.1);border-radius:4px}
.chart-wrap{border-radius:var(--radius)}
canvas{display:block;max-width:100%}
#panel-charts .glass{max-height:260px;overflow:hidden}
#panel-charts canvas{max-height:240px}
#panel-overview .glass canvas{max-height:220px}
```

### 1.17 Profil-/Markt-Karten (Phase 11)

```css
#profil-karten{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0}
.profil-karte{
  background:var(--card-bg);backdrop-filter:blur(20px) saturate(1.4);
  border:1px solid var(--card-border);border-radius:10px;
  padding:5px 10px;min-width:108px;box-shadow:var(--shadow);
}
.profil-karte.shadow{border-left:3px solid var(--amber)}
.profil-karte.live{border-left:3px solid var(--green)}
.profil-karte .pk-markt{font-size:9.5px;font-weight:700;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.5px}
.profil-karte .pk-name{font-size:12px;font-weight:600;color:var(--text);margin:1px 0}
.profil-karte .pk-badge{font-size:9px;font-weight:600;margin:2px 0}
.profil-karte.shadow .pk-badge{color:var(--amber)}
.profil-karte.live .pk-badge{color:var(--green)}
.profil-karte .pk-info{font-size:9.5px;color:var(--text-dim)}
```

### 1.18 Header (Sticky, inline gestylt)

```html
<header style="position:sticky;top:0;z-index:50;background:rgba(255,255,255,.75);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);margin:-16px -20px 10px;border-bottom:1px solid rgba(15,23,42,.07)">
  <img src="/assets/banner.png" alt="Micro Trader System" style="width:100%;height:90px;display:block;object-fit:contain;object-position:center;background:#0b1220">
  <div style="display:flex;align-items:center;gap:10px;padding:8px 20px">
    <img src="/assets/logo.png" alt="Logo" style="width:32px;height:32px;border-radius:8px">
    <span style="font-size:16px;font-weight:700">Micro-Trader</span>
    <span id="updateTime" style="font-size:12px;color:var(--text-dim)">lade…</span>
    <span id="marketStatus" style="font-size:10px;font-weight:400;margin-left:4px"></span>
    <span id="boersenDisplay" style="font-size:10px;font-weight:400;margin-left:6px"></span>
    <span id="notifBadge" style="display:none;margin-left:auto;font-size:11px;background:#dc2626;color:#fff;padding:1px 7px;border-radius:10px;cursor:pointer" onclick="showTab('charts')">🔔</span>
    <span id="versionBadge" style="margin-left:8px;font-size:10px;color:var(--text-dim);font-weight:400;white-space:nowrap"></span>
    <div id="userArea" style="margin-left:auto;position:relative;display:flex;align-items:center;gap:8px;cursor:pointer;padding:4px 8px;border-radius:10px;transition:background .15s" onclick="toggleUserMenu(event)" onmouseover="this.style.background='rgba(15,23,42,.05)'" onmouseout="this.style.background='transparent'">
      <div id="userAvatar" style="width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--accent-dark));color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0">…</div>
      <div style="line-height:1.15">
        <div id="userName" style="font-size:12px;font-weight:600;color:var(--text)">…</div>
        <div id="userRole" style="font-size:9.5px;color:var(--text-dim)">…</div>
      </div>
      <span style="font-size:9px;color:var(--text-dim)">▾</span>
      <div id="userMenu" style="display:none;position:absolute;right:0;top:calc(100% + 6px);min-width:210px;background:var(--glass-strong);backdrop-filter:blur(20px);border:1px solid var(--card-border);border-radius:14px;box-shadow:var(--shadow-lg);padding:6px;z-index:100">
        <!-- Menüpunkte: Mein Konto, Einstellungen, Admin-Bereich (nur Admins), Abmelden -->
      </div>
    </div>
  </div>
</header>
```

**Header-Aufbau:** Sticky-Header mit Banner-Bild (90px hoch, `object-fit:contain`
auf dunklem Grund `#0b1220`), darunter Logo (32px, abgerundet 8px) + Titel
(16px/700) + Live-Zeit + Marktstatus + Börsen-Anzeige + roter 🔔-Badge +
Version-Badge + rechts User-Avatar (30px Kreis, `linear-gradient(135deg,#2563eb,#1d4ed8)`,
weiße Initiale) mit Dropdown-Menü.

### 1.19 Typografie-Hierarchie (Zusammenfassung)

| Element | Größe | Gewicht | Farbe | Sonstiges |
|---|---|---|---|---|
| h1 (Seitentitel) | 27px | 700 | `--text` | `letter-spacing:-0.5px` |
| Karten-Wert (`.wert`) | 20px | 700 | `--text` | `letter-spacing:-0.5px` |
| Stat-Zahl (`.stat .num`) | 22px | 700 | `--text` | — |
| Tabellen | 12.5px | 400 | `--text` | th: 11px/500/uppercase |
| Tab-Label | 11.5px | 500 | `--text-dim` | aktive: `--text` |
| Karten-Label (h3) | 12px | 500 | `--text-dim` | uppercase, `letter-spacing:0.6px` |
| Meta/klein | 9.5–11px | 400–600 | `--text-dim`/`--text3` | — |

---

## 2. Admin-Bereich (`dashboard.py` — `ADMIN_CSS`)

Wörtlich (Z2216–2260):

```css
:root{--bg1:#f8fafc;--bg2:#f1f5f9;--card-bg:rgba(255,255,255,.82);--card-border:rgba(15,23,42,.07);
--accent:#2563eb;--accent-dark:#1d4ed8;--green:#10b981;--amber:#f59e0b;--red:#ef4444;
--text:#0f172a;--text-dim:#64748b;--radius:14px;--r-lg:18px;
--shadow:0 10px 28px rgba(15,23,42,.08);--shadow-lg:0 24px 48px rgba(61,93,153,.12)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;background:linear-gradient(160deg,var(--bg1),var(--bg2));
background-image:radial-gradient(ellipse at 15% 0%,rgba(37,99,235,.07) 0%,transparent 55%),radial-gradient(ellipse at 85% 0%,rgba(16,185,129,.05) 0%,transparent 50%);
min-height:100vh;color:var(--text);-webkit-font-smoothing:antialiased}
.wrap{max-width:1100px;margin:0 auto;padding:24px 20px 60px}
.top{display:flex;align-items:center;gap:14px;margin-bottom:22px}
.top img{width:40px;height:40px;border-radius:10px}
.top h1{font-size:21px;font-weight:700}
.top .sub{font-size:11.5px;color:var(--text-dim)}
.top .right{margin-left:auto;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.pill{background:var(--card-bg);backdrop-filter:blur(10px);border:1px solid var(--card-border);border-radius:999px;padding:6px 14px;font-size:12px;font-weight:600;box-shadow:var(--shadow)}
a.pill{color:var(--accent);text-decoration:none}
.nav{display:flex;gap:4px;background:rgba(118,118,128,.10);padding:4px;border-radius:999px;margin-bottom:22px;overflow-x:auto;scrollbar-width:none}
.nav a{padding:7px 16px;border-radius:999px;font-size:12.5px;font-weight:600;color:var(--text-dim);text-decoration:none;white-space:nowrap;transition:all .18s}
.nav a:hover{color:var(--text)}
.nav a.active{background:#fff;color:var(--text);box-shadow:0 1px 4px rgba(0,0,0,.1)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:22px}
.stat{background:var(--card-bg);backdrop-filter:blur(14px);border:1px solid var(--card-border);border-radius:var(--radius);padding:16px;box-shadow:var(--shadow)}
.stat .num{font-size:22px;font-weight:700;margin-bottom:2px}
.stat .lbl{font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:.05em}
.glass{background:var(--card-bg);backdrop-filter:blur(14px);border:1px solid var(--card-border);border-radius:var(--radius);padding:18px 20px;box-shadow:var(--shadow);margin-bottom:14px}
.glass h2{font-size:14px;font-weight:700;margin-bottom:12px;color:var(--text)}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--text-dim);font-size:10.5px;text-transform:uppercase;letter-spacing:.04em;padding:8px 10px;border-bottom:1px solid var(--card-border)}
td{padding:9px 10px;border-bottom:1px solid var(--card-border);vertical-align:top}
tr:last-child td{border-bottom:none}
code{background:rgba(15,23,42,.06);padding:2px 7px;border-radius:6px;font-size:11.5px}
.b{font-weight:600}
.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}
.btn{display:inline-block;padding:8px 16px;border-radius:10px;border:none;cursor:pointer;font-size:12.5px;font-weight:600;font-family:inherit;transition:all .15s;text-decoration:none}
.btn.primary{background:var(--accent);color:#fff}.btn.primary:hover{background:var(--accent-dark)}
.btn.ghost{background:transparent;border:1px solid var(--card-border);color:var(--text)}
.btn.ghost:hover{background:rgba(15,23,42,.05)}
.btn.danger{background:rgba(239,68,68,.12);color:var(--red)}
.hint{font-size:11px;color:var(--text-dim);margin-top:10px}
.src{display:inline-block;font-size:9.5px;font-weight:700;border-radius:6px;padding:1px 7px;text-transform:uppercase;letter-spacing:.03em}
.src-tenant{background:rgba(37,99,235,.12);color:var(--accent)}
.src-global{background:rgba(118,118,128,.14);color:var(--text-dim)}
.src-default{background:rgba(16,185,129,.12);color:var(--green)}
```

**Admin-Layout-Struktur:**
- `.wrap` max-width **1100px**, zentriert
- `.top`: Logo 40px + Titel „🔧 Admin-Bereich" (21px/700) + Subtitle + rechts Pills (User · Rolle · MFA-Status, Dashboard-Link, Logout)
- `.nav`: 8 Pill-Tabs (📊 Übersicht, 🩺 System, 👥 Benutzer, 🏢 Mandanten, 🌐 Logins, 🛡️ Sicherheit, 📜 Audit, 💾 Backups)
- `.cards`: Stat-Cards (Benutzer, Aktiv, MFA aktiv, Sessions, Audit, Login-Fails, Backups, Trading-Status)
- `.glass`: Karten-Panels mit h2-Titeln
- Buttons: `.btn.primary` (blau gefüllt), `.btn.ghost` (transparent), `.btn.danger` (rot transluzent)
- Quell-Badges: `.src-tenant` (blau), `.src-global` (grau), `.src-default` (grün)

**Unterschiede zum Dashboard:** Admin nutzt `--card-bg` 82% (statt 78%), kein
`--text2/--text3`, `backdrop-filter:blur(14px)` statt 24px, `.nav a` mit
`font-weight:600` statt 500.

---

## 3. Login / MFA (kein Custom-CSS)

Wörtlich (dashboard.py Z2053–2056):

```html
<form method='POST'>Benutzer:<input name='username'><br>
Passwort:<input name='password' type='password'><br>
<input type='submit' value='Login'></form>
```

MFA-Form (Z2086–2088):

```html
<form method='POST'>MFA-Code:<input name='code'><br>
<input type='submit' value='OK'></form>
```

**Bewusst ungestylt** — Browser-Defaults. Fehlerfälle: 429 „Zu viele
Fehlversuche", 401 „Login fehlgeschlagen" (nackte `<h1>`-Seiten).

---

## 4. Design-System-Zusammenfassung (Kurzfassung für KI-Check)

### Farbpalette
- **Primär/Akzent:** `#2563eb` (Blau 600), Hover `#1d4ed8`
- **Hintergrund:** `#f8fafc` → `#f1f5f9` (linear-gradient 160°) + 2 radiale
  Farbwolken (blau 8% oben-links, grün 6% oben-rechts)
- **Text:** `#0f172a` (Slate 900), sekundär `#64748b`, tertiär `#94a3b8`
- **Status:** grün `#10b981`, amber `#f59e0b`, rot `#ef4444`, violett `#8b5cf6`
- **Karten:** `rgba(255,255,255,.78)` mit Blur
- **Badge-Muster:** Pastell-BG + satte Textfarbe gleicher Familie

### Typografie
- **Font:** `'Segoe UI Variable','Segoe UI',system-ui,-apple-system,sans-serif`
- **Zahlen:** `font-variant-numeric:tabular-nums` (Tabellen, .num, td, th)
- **Stil:** weiche große Zahlen (700er, leicht negatives letter-spacing),
  Uppercase-Labels mit letter-spacing 0.4–0.6px, sehr kleine Meta-Texte (9.5–11px)

### Glassmorphismus
- Dashboard: `blur(24px) saturate(180%)` bei `.glass`
- Cards: `blur(10px) saturate(1.3)`
- Header/UserMenu: `blur(20px)`
- Schatten: `0 10px 28px rgba(15,23,42,.08)` (ruhend), `0 24px 48px rgba(61,93,153,.12)` (Hover)
- Inset-Highlight: `inset 0 1px 0 rgba(255,255,255,.7)` + `::after`-Rand unten/rechts

### Radien
- Basis `14px`, groß `18px`, klein `10px`, Pills/Tabs `999px`, Badges `4px`,
  Topics `10px`, Scrollbar-Thumb `4px`

### Animationen
- Tab-Wechsel: `all .18s cubic-bezier(.32,.72,0,1)`
- Panel-Fade: `fadeIn 0.25s` (translateY 8px + scale .99)
- Hover: `translateY(-1px)` mit Schattenwechsel (`.glass`, `.card`)

### Responsive
- `.two-col` → 1 Spalte unter 700px
- `.grid`: `repeat(auto-fill,minmax(230px,1fr))`
- Tabs/Nav: `overflow-x:auto` mit ausgeblendetem Scrollbar

---

*Generiert 2026-08-09 · Quelle: dashboard.html (Z1–287) + dashboard.py
(ADMIN_CSS Z2216–2260, login/mfa Z2025–2100) · Stand v2.43.0*
