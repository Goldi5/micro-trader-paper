# Micro-Trader — Umsetzungsplan (strikt nach §28 Aufbauphasen)

**Erstellt:** 2026-08-06
**Basis:** `Micro-Trader-Zielarchitektur.md` §22, §28, §29.A/B
**Workflow:** Plan → Plan prüfen → Dev-Clone umbauen/testen → bei grün in Live spiegeln

---

## Phase 2 — Identität & Struktur (§4, §29.A)

### Ziel
Profil-System als Grundlage für Multi-Markt (US/DE/JP). Kein User/Rollen-Modell (Singleton reicht), aber **Profil-Objekt** mit märkte[], depotarten[], base_currency, modus.

### Tasks (aus §29.A)
1. **Profil-Schema** (`profil_schema.py` neu): JSON-Schema für Profil-Objekt
   - Felder: `name`, `märkte[]`, `depotarten[]`, `risk_model`, `news_sources[]`, `data_sources[]`, `base_currency`, `handelszeiten`, `regelstand_ref`, `modus` (shadow/paper/live)
2. **US_Test_Shadow** Profil anlegen (Basis, vorhandene Logik) → `profile_us_shadow.json`
3. **DE-Markt-Modell** vorbereiten (§29.A): Xetra/Frankfurt, EUR, CET, DE-Feiertage, DAX-Nähe
4. **JP-Markt-Modell** vorbereiten (§29.A): TSE/Nikkei, JPY, JST, JP-Feiertage
5. **Regime pro Markt separat** (§9): US/DE/JP je eigene Regime-Logik

### Dateien
- `profil_schema.py` (NEU)
- `profile_us_shadow.json` (NEU)
- `profile_de_shadow.json` (NEU, vorbereitet)
- `profile_jp_shadow.json` (NEU, vorbereitet)
- `boersen.py` erweitern (DE/JP Börsen)

### Risiko
Niedrig (nur Datenstrukturen, kein Trading-Eingriff)

### Verifikation
- `python profil_schema.py --validate` → alle 3 Profile gültig
- `boersen.ist_offen("DE")` / `("JP")` liefert korrekte Zeiten

---

## Phase 3 — Marktmodell (§5, §29.A)

### Ziel
Märkte US/DE/JP mit korrekter Zeitzonen/Feiertags-Logik. Symbol-Mapping pro Markt.

### Tasks
1. **DE-Börsenkalender**: Xetra/Frankfurt Handelszeiten (09:00-17:30 CET), DE-Feiertage
2. **JP-Börsenkalender**: TSE 09:00-11:30, 12:30-15:00 JST, JP-Feiertage
3. **Symbol-Mapping** (§11): Ticker + Börse + Land + Währung + interne ID
   - US: `AAPL` (NASDAQ, USD)
   - DE: `SAP.DE` (Xetra, EUR) oder `SIE.DE`
   - JP: `7203.T` (TSE, JPY)
4. **Regime pro Markt** (§9): separate Regime-Berechnung

### Dateien
- `boersen.py` (erweitert: DE/JP)
- `symbol_mapping.py` (NEU)

### Risiko
Mittel (Zeitzonen/Feiertage fehleranfällig)

### Verifikation
- `boersen.ist_offen("US")` / `("DE")` / `("JP")` korrekt
- Symbol-Mapping löst `SAP.DE` → Xetra/EUR

---

## Phase 4 — Handelsuniversum / Datenquellen (§8, §29.B)

### Ziel
Datenquellen-Matrix für US/DE/JP. Kursdaten DE/JP via yfinance-Suffix.

### Tasks
1. **Kursdaten DE**: yfinance Xetra-Ticker (`SAP.DE`) testen
2. **Kursdaten JP**: yfinance TSE-Ticker (`7203.T`) validieren
3. **News DE/JP**: regionale Quellen (finanzen.net, JP-Feed) — Platzhalter
4. **Makrodaten**: Zinsen/Inflation pro Markt — Platzhalter
5. **Datenqualität-Check** (§8): Vollständigkeit, Aktualität, Symbolkorrektheit

### Dateien
- `marktdaten.py` erweitern (DE/JP Suffix-Handling)
- `datenqualitaet.py` (NEU, Basis-Check)

### Risiko
Mittel (neue yfinance-Suffixe, Rate-Limits)

### Verifikation
- `hole_kurs("SAP.DE")` liefert EUR-Kurs
- `hole_kurs("7203.T")` liefert JPY-Kurs

---

## Reihenfolge (strikt §28)
1. **Phase 2** (Profil-Schema + US-Profil) ← START
2. Phase 2 (DE/JP-Modell vorbereiten)
3. **Phase 3** (Börsenkalender DE/JP + Symbol-Mapping)
4. **Phase 4** (Datenquellen DE/JP + Qualitäts-Check)
5. Danach: Phase 10 (Daily PDF), Phase 11 (Dashboard-Karten)

**Nicht in diesem Plan:** Phase 13 (Live-Freigabe) — wartet auf User-Freigabe (§29.F).

---

## Status-Tracking
| Phase | Task | Status |
|---|---|---|
| 2.1 | Profil-Schema | ✅ |
| 2.2 | US_Test_Shadow Profil | ✅ |
| 2.3 | DE-Markt-Modell vorbereiten | ✅ |
| 2.4 | JP-Markt-Modell vorbereiten | ✅ |
| 2.5 | Regime pro Markt | ✅ |
| 3.1 | DE-Börsenkalender | ✅ |
| 3.2 | JP-Börsenkalender | ✅ |
| 3.3 | Symbol-Mapping | ✅ |
| 4.1 | Kursdaten DE | ✅ |
| 4.2 | Kursdaten JP | ✅ |
| 4.3 | Datenqualität-Check | ✅ |
