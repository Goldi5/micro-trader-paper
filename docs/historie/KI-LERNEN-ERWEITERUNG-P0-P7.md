# Micro-Trader — KI-Lernen Erweiterung (Phase 0–7)

**Stand:** 01.08.2026 14:30 · **System:** Windows 11, Python 3.12, yfinance, Flask :5300
**Umfang:** Vollständige Implementierung der Spezifikation §3.1–§3.8 (Opportunitätskosten, Reflexion, Regel-Schema, Swap-Logik, Konfidenz, Regime, Skill-Sync, Cross-Depot)
**Alle Zahlen aus echten Dateien zum Stand 01.08. 14:30.**

---

## 1. ARCHITEKTUR NACH DEM AUSBAU

```
Cron (Hermes, 15 Min) → micro-trader-cron.py
  ├─detached→ micro-trader-pipeline.py (News → KI-News → Trader → Lernen → Skill-Sync)
  └─So 00:00→ ki_reflexion.reflexion_wochenbericht()  (Phase 1)

KI-Entscheidung (ki_decisions.py):
  kontext_block() liefert jetzt zusätzlich:
    • ⚠ Konzentration (≥N Depots)
    • 🏭 Sektor (via kategorie_fuer_ticker)
    • 📊 Fundamentals (24h-Cache)
    • 🎯 Selbst-Statistik
    • 📈 ATR % + Vol-Ratio
    • 📈 Multi-Timeframe (1h + 15min)        [P3]
    • 🌐 MARKTREGIME (Bull/Bear/Seitwärts)    [P5]
  + lade_lern_kontext() fügt ein:
    • 📌 Gewichtete Regeln (aus learned_rules.json)
    • 📊 Konfidenz-Kalibrierung (Bins)         [P4]

Lernen (ki_learning.py, alle 3 Min via Pipeline):
  analisiere_entscheidungen():
    • P2+ Swap-Score (Opportunitätskosten)
    • P3 mehrstufiges Lerneffekt (15m/4h/1d + ATR)
    • P4 Konfidenz-Binning → konfidenz_stats.json
    • Sektor + Regime-Tag pro Log-Eintrag       [P5]
    • News-Lernschleife, Exit-Qualität, Anti-Muster (P1)
  → speichere_regeln() → learned_rules.py (Source of Truth)

Skill-Fütterung:
  • learned_rules.json → skill_sync.py → references/aktuelle-ki-regeln.md
  • Regeln fließen in jeden KI-Prompt via lade_lern_kontext()
  • ki_reflexion.wochenbericht → pending_rules.json + reflexion_summary_Www.md
```

---

## 2. PHASE 0 — `learned_rules.json` (Source of Truth)

**Datei:** `learned_rules.py` (neu) + `learned_rules.json` (Schema 1.0)

**Schema einer Regel:**
```json
{
  "id": "r_20260801_64952",
  "muster": "[Swap] Kapital in schwachen Positionen blockiert Benchmark",
  "regel": "Gehaltene Positionen liefen Ø +1.4% schlechter als Benchmark (SPY)...",
  "typ": "swap",                    // swap | positiv | anti | opportunitaet
  "gewicht": 2.0,                   // Roh-Gewicht
  "support_count": 25,              // wie oft bestätigt
  "violation_count": 0,             // wie oft widerlegt
  "avg_effect_when_applied": 1.41,
  "kontext": {                      // S3.3.1 Kontextbedingungen
    "asset_klasse": [], "sektor": [], "vix_range": [0, 999],
    "trend_4h": "", "regime": ["bear", "seitwaerts"], "min_konfidenz": 0
  },
  "created_at": "2026-08-01T14:25:00", "updated_at": "...", "last_seen_at": "...",
  "decay_lambda": 0.01,             // pro Tag
  "effektiv_gewicht": 2.0           // gewicht * exp(-lambda * tage)
}
```

**Decay-Formel (S3.3.3):** `effektiv_gewicht = gewicht * exp(-0.01 * tage)`

**Migration:** `migriere_aus_ki_regeln()` hat die 12 alten Regeln aus `ki_regeln.json` übernommen (Metriken aus Regel-Text geparst).

**Kompatibilität:** `ki_regeln.json` wird weiterhin als Export geschrieben (alte Loader funktionieren).

**Status:** 13 Regeln (1 swap + 1 positiv + 11 anti).

---

## 3. PHASE 1 — `ki_reflexion.py` in Pipeline

**Trigger:** Sonntag 00:00 Uhr (in `micro-trader-cron.py` via `weekday()==6`).

**Funktion `reflexion_wochenbericht()` (deterministisch, kein KI-Call):**
- Analysiert 184 Entscheidungen (7 Tage)
- Cluster nach Asset-Klasse (crypto/lev-etf/volatility/core) × Aktion
- Top-3 Fehlermuster + Top-3 Erfolgsmuster
- Schreibt:
  - `reflexion_summary_2026-W30.md` (lesbar)
  - `pending_rules.json` (3 Kandidaten zur Freigabe)

**Echte `pending_rules.json` (01.08.):**
| Muster | Typ | G | Violations |
|--------|-----|---|-----------|
| [Reflexion] halten bei core | positiv | 2.0 | 116 |
| [Reflexion] halten bei lev-etf | anti | 2.0 | 26 |
| [Reflexion] halten bei volatility | anti | 2.0 | 12 |

→ Die KI "hält" systematisch zu oft (116× bei core-Titeln widerlegt).

**Hinweis:** `selbst_reflexion(force=True)` (KI-Call-Variante) existiert seit vorher, läuft aber nur manuell — nicht im Cron (Kosten). Der wöchentliche Bericht ist rein deterministisch.

---

## 4. PHASE 2 — Swap/Counterfactual (Opportunitätskosten)

**Funktion `swap_score_berechnen(decisions)`:**
- Für jede "halten"-Position: eigene 4h-Performance vs. Benchmark (SPY 1d)
- `swap_score = benchmark_ret - eigen_ret` (positiv = Alternative war besser)
- Schwelle: swap_score ≥ 2.0 → "verpasste Umschichtung"

**Echte Messung (01.08.):**
```
ges: 98 gehaltene Positionen
swaps: 25 (≥2% schlechter als SPY)
avg_swap: +1.41% (Ø Lücke zum Benchmark)
Benchmark (SPY 1d): +1.62%
Beispiele:
  KOLD:  eigen -2.53%  vs SPY +1.62%  → swap +4.14
  RIOT:  eigen -1.94%  vs SPY +1.62%  → swap +3.56
  MRNA:  eigen -4.09%  vs SPY +1.62%  → swap +5.71
```

**Regel-Vorschlag `_swap_regel_vorschlag()`:** Bei `avg_swap ≥ 1.0` + `swaps ≥ 2` → speichert `[Swap]`-Regel.

**Resultat:** `[Swap] Kapital in schwachen Positionen blockiert Benchmark` (G 2.0, sup=25) ist jetzt in `learned_rules.json`.

---

## 5. PHASE 3 — Mehrstufiges Lernsignal + Risikoadjustierung

**Funktion `lerneffekt_multiskalen(ticker, aktion)`:**
```
s15 = lerneffekt(aktion, change_15m)[0]   # 15min-Bars (neue Funktion hole_kurs_entwicklung_intervall)
s4  = lerneffekt(aktion, change_4h)[0]    # 1h-Bars (4h)
s1  = lerneffekt(aktion, change_1d)[0]    # 1h-Bars (24h)
kombi = 0.3*s15 + 0.5*s4 + 0.2*s1          # S3.2 Gewichtung
wert = round(kombi)  →  auf [-5, +5] geklemmt
```

**ATR-Normalisierung (S3.2.2):** Bei `atr_pct > 5.0` (spekulative Titel) → Signal auf 70% gedämpft (weniger hartes "−5").

**Test (01.08., Wochenende — Bars teils leer, Fallback 4h/1d):**
```
RIOT:  wert=-2 (teilfehler) | 15m=-2.46 4h=-1.94 1d=+0.75 | atr=5.77 (>5 → Dämpfung)
KOLD:  wert=-4 (fehler)     | 15m=-1.11 4h=-2.53 1d=-2.78
NVDA:  wert=-3 (fehler)     | 15m=+0.92 4h=+1.41 1d=+4.79
AAPL:  wert=-4 (fehler)     | 15m=+2.05 4h=+2.82 1d=-9.42
```

→ Mehrstufiges Signal unterscheidet kurzfristig (15m) von mittel/long (4h/1d).

---

## 6. PHASE 4 — Konfidenz-Kalibrierung

**Funktion `konfidenz_kalibrierung()` (S3.5):**
- Sammelt (konfidenz, lerneffekt) aus 184 learned-Einträgen
- Bins: 0-20, 20-40, 40-60, 60-80, 80-100
- Pro Bin: Trefferquote (LE≥1) + Ø Lerneffekt
- Schreibt `konfidenz_stats.json`

**Echte Bins (01.08.):**
| Bin | Treffer | Ø LE | n |
|-----|---------|------|---|
| 20-40 | 2% | -2.9 | 41 |
| 40-60 | 3% | -2.9 | 34 |
| 60-80 | 5% | -2.7 | 87 |
| 80-100 | **0%** | -3.3 | 22 |

**Befund:** Die KI ist bei ALLEN Konfidenz-Stufen schwach. 80-100% Konfidenz = **0% Treffer** → die KI überschätzt sich massiv. Dieser Befund steht jetzt im KI-Prompt ("Passe deine Konfidenz so an, dass hohe Werte nur bei klaren Setups!").

---

## 7. PHASE 5 — Sektor + Regime-Tags

**`boersen.markt_regime(benchmark="SPY")`:**
```
Bull:      Kurs > SMA200 && SMA50 > SMA200
Bear:      Kurs < SMA200 && SMA50 < SMA200
Seitwärts: sonst
```
Lädt 1y-Tagesdaten, berechnet 50d/200d-Linien.

**Echte Messung (01.08.):** 🟢 **Bull** (SPY über 200d-Linie, Aufwärtstrend)

**Integration:**
- `ki_kontext.kontext_block()` fügt `MARKTREGIME: 🟢 Bull (S&P 500 vs. 200-Tage-Linie)` in jeden KI-Prompt
- `ki_learning.analysiere_entscheidungen()` schreibt `sektor` + `regime` in jeden learned-Log-Eintrag

---

## 8. PHASE 6 — Skill-Sync optimiert

**`skill_sync.py`:**
- Lädt aus `learned_rules.json` (nicht mehr `ki_regeln.json`)
- `aktuelle-ki-regeln.md` hat jetzt **Kurzfassung (Top-5)** am Anfang (3-5 komprimierte Sätze)
- Danach die detaillierten Regel-Blöcke (⭐ positiv / ⚠ anti)

**Beispiel-Kurzfassung (01.08.):**
```
## 📋 Kurzfassung (Top-5)
- **Regel:** Gehaltene Positionen liefen Ø +1.4% schlechter als Benchmark (SPY)...
- **Regel:** Verkäufe kommen zu früh – Kurs lief nach Verkauf im Schnitt +4.4% weiter...
- **Verbot:** NICHT halten bei meme-Titeln – systematisch falsch (2/3 widerlegt, Ø -2.0)...
- **Verbot:** NICHT halten bei index-Titeln – systematisch falsch (3/3 widerlegt, Ø -2.0)...
- **Verbot:** NICHT halten bei biotech-Titeln – systematisch falsch (2/4 widerlegt, Ø -2.5)...
```

---

## 9. PHASE 7 — Cross-Depot-Lernen

**`learned_rules.cross_depot_lernen()`:**
- Liest alle Regeln, gruppiert nach (muster, typ)
- Regeln in ≥2 Depots → globales Muster (`learned_rules_global.json`)
- `global: True`-Flag für künftige Depot-spezifische Regeln

**Status (01.08.):** `learned_rules_global.json` existiert, aber **0 globale Muster** — weil alle aktuellen Regeln bereits global sind (nicht depot-spezifisch). Die Infrastruktur ist bereit für echte Depot-spezifische Regeln (noch nicht im System).

---

## 10. DIE 13 REGELN IM DETAIL (`learned_rules.json`, 01.08.)

| # | Typ | Gewicht | Muster | Befund |
|---|-----|---------|--------|--------|
| 1 | **swap** | +2.00 | [Swap] Kapital blockiert Benchmark | 25 Swaps, Ø +1.4% schlechter |
| 2 | positiv | +0.90 | [Exit] Verkauf bei laufendem Trend | Take-Profit großzügiger |
| 3 | anti | -1.41 | [Anti] halten bei meme-Titeln | 2/3 widerlegt |
| 4 | anti | -1.47 | [Anti] halten bei index-Titeln | 3/3 widerlegt |
| 5 | anti | -1.55 | [Anti] halten bei biotech-Titeln | 2/4 widerlegt |
| 6 | anti | -1.62 | [Anti] halten bei ev-Titeln | 2/3 widerlegt |
| 7 | anti | -1.64 | [Anti] halten bei space-Titeln | 3/3 widerlegt |
| 8 | anti | -1.67 | [Anti] halten bei commodity-Titeln | 5/6 widerlegt |
| 9 | anti | -1.69 | [Anti] halten bei lev-bear-Titeln | 3/4 widerlegt |
| 10 | anti | -1.69 | [Anti] halten bei ai-Titeln | 5/5 widerlegt |
| 11 | anti | -1.82 | [Anti] halten bei crypto-Titeln | 6/6 widerlegt |
| 12 | anti | -1.86 | [Anti] halten bei lev-bull-Titeln | 5/5 widerlegt |
| 13 | anti | -1.88 | [Anti] halten bei volatility-Titeln | 3/3 widerlegt |

---

## 11. OFFENE PUNKTE / HINWEISE

| Punkt | Status |
|-------|--------|
| `ki_reflexion.self_reflexion()` (KI-Call) im Cron | ❌ nur manuell (Kosten), Bericht ist deterministisch |
| `learned_rules_global.json` mit echten Depot-Regeln | ⚠️ Infrastruktur da, aber noch keine depot-spezifischen Regeln im System |
| Pending-Rules automatisch freigeben | ❌ manuell (im Skill als `pending_rules.json`) |
| Port 5299 | ❌ Zombie (kein Admin-Kill) → Dashboard auf 5300 |

---

## 12. FÜR EINE ANDERE KI — KOMPAKT

**Eingebaut (P0–P7):**
- Strukturiertes Regel-Schema mit Decay (`learned_rules.json`)
- Wöchentlicher Reflexionsbericht (`pending_rules.json`)
- Swap/Opportunitätskosten-Messung (25/98 Positionen schlechter als SPY)
- Mehrstufiges Lernsignal (15m/4h/1d) + ATR-Dämpfung
- Konfidenz-Binning (80-100% = 0% Treffer → KI überschätzt sich)
- Sektor + Marktregime-Tags (aktuell Bull)
- Skill-Sync mit Kurzfassung
- Cross-Depot-Infrastruktur

**Nicht eingebaut:**
- KI-Reflexion automatisch (nur deterministischer Bericht)
- Auto-Freigabe von Pending-Rules
- Echte Depot-spezifische Regeln (noch alle global)

**System-Zustand:** 13 Regeln, Trefferquote 3,3%, Ø LE −2.86, Rendite −16,28%. Die KI lernt jetzt Verbote + Swap + Konfidenz-Warnung, aber ist weiterhin schwach (überwiegend "halten" bei fallenden Titeln).
