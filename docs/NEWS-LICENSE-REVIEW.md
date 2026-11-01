# NEWS-LICENSE-REVIEW — Phase 0

> Lizenzprüfung der News-Quellen. Stand: 2026-08-12 · v2.57.1.
> **STATUS: UNVERIFIED** — Lizenzbedingungen wurden nicht juristisch geprüft.
> Dieses Dokument sammelt offene Fragen, keine Freigabe.

## 1. Quellen + Lizenzstatus

| ID | Quelle | URL | Lizenzstatus | Kommerzielle Nutzung | Evidence |
|---|---|---|---|---|---|
| S1 | Bloomberg Markets | `feeds.bloomberg.com/markets/news.rss` | **UNVERIFIED** | unklar | RSS ist öffentlich, aber Bloomberg-TOS schränkt Weiterverwertung ein |
| S2 | Dow Jones / MarketWatch | `feeds.content.dowjones.io/.../mw_topstories` | **UNVERIFIED** | unklar | Dow Jones TOS: kommerzielle Weiterverwertung typ. lizenzpflichtig |
| S3 | Yahoo Finance | `finance.yahoo.com/news/rssindex` | **UNVERIFIED** | unklar | Yahoo TOS regelt API/Nutzung |
| S4 | NYT Economy | `rss.nytimes.com/.../nyt/Economy.xml` | **UNVERIFIED** | unklar | NYT TOS: RSS nur für persönliche Nutzung |
| S5 | Investopedia | `investopedia.com/feedbuilder/...` | **UNVERIFIED** | unklar | Investopedia TOS |

## 2. Risiken (bei späterem Live-Betrieb)

- **Marktdaten/News als Entscheidungsgrundlage:** Selbst bei Paper/Shadow fließen
  News in KI-Entscheidungen. Kommerzielle Weiterverwertung (Live-Trading) erfordert
  geklärte Lizenz.
- **Redistribution:** Das Speichern + Anzeigen im Dashboard ist "interne Nutzung"
  (Paper), aber ein Live-System mit mehreren Tenants könnte als Weitergabe gelten.
- **Attribution:** Viele Feeds fordern Quellen-Nennung.

## 3. Offene Fragen (muss vor Phase 11/13 geklärt werden)

- [ ] Darf RSS-Inhalt als **Trading-Signal-Input** genutzt werden (auch nur Paper)?
- [ ] Erfordert Live-System eine **kommerzielle News-Lizenz** (Bloomberg/Dow Jones)?
- [ ] Reicht **Attribution** (Quelle anzeigen) oder wird Inhalt verlangt?
- [ ] Ticker-Mapping aus Nachrichten: verletzt das Quell-TOS?

## 4. Empfehlung (vorläufig, nicht rechtsverbindlich)

1. **Paper/Shadow (Phase 0–6):** RSS-Nutzung als Forschungs-/Lern-Input ist unkritisch,
   solange keine kommerzielle Weitergabe erfolgt. Attribution im Dashboard anzeigen.
2. **Live-System (Phase 7+):** Vor Aktivierung **explizite Lizenzklärung** einholen
   (juristisch oder via lizenzfreie Quellen wie SEC-EDGAR, Unternehmens-IR).
3. **Fallback-Quellen (lizenzfrei):** SEC EDGAR Full-Text Feeds, Unternehmens-Pressemeldungen
   (Investor-Relations) — für Live-Betrieb prüfen.

## 5. Nächste Schritte

- Bis Phase 11: Lizenzstatus mit User klären (keine Annahme).
- Bis Phase 13: bei Bedarf auf lizenzfreie Quellen umstellen.
- Dieses Dokument ist **KEINE Freigabe** — nur Sammlung offener Punkte.

> **HINWEIS:** Der Agent darf keine rechtliche Einschätzung abgeben. UNVERIFIED bleibt
> stehen, bis der User eine Lizenzbestätigung liefert.
