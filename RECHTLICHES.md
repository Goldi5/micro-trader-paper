# Rechtliche Hinweise

## Keine Anlageberatung – Haftungsausschluss

Micro-Trader ist ein privates **Experimentier- und Lernprojekt** für Paper-Trading mit virtuellem Geld.

- Nichts in diesem Repository ist eine Anlageberatung, Anlageempfehlung oder Aufforderung zum Kauf oder Verkauf von Finanzinstrumenten.
- Ergebnisse aus dem Paper-Trading sagen nichts über künftige Ergebnisse mit echtem Geld aus. Der Handel mit Wertpapieren, insbesondere mit Hebel-Produkten, kann zum **Totalverlust** führen.
- KI-Entscheidungen können falsch, unvollständig oder unvorhersehbar sein.
- Die Software wird **ohne jede Gewährleistung** bereitgestellt. Wer sie nutzt, verändert oder mit echtem Geld betreibt, tut das auf eigenes Risiko und in eigener Verantwortung.
- Echter Handel ist im Code bewusst gesperrt (`PAPER_ONLY`). Wer diese Sperre entfernt, trägt die volle Verantwortung, auch für die Einhaltung aufsichtsrechtlicher und steuerlicher Pflichten.

## Datenquellen und Dienste Dritter

Das Repository enthält **keine** Marktdaten, Nachrichtentexte oder Zugangsdaten. Diese werden zur Laufzeit von den jeweiligen Anbietern abgerufen und lokal zwischengespeichert. Die Zwischenspeicher sind git-ignoriert und werden nicht weitergegeben. Für jeden Anbieter gelten dessen Nutzungsbedingungen. Wer das System betreibt, muss sie selbst prüfen und einhalten.

| Anbieter | Verwendung | Hinweis |
|---|---|---|
| Yahoo Finance (über das Paket `yfinance`) | Kurse, Kennzahlen, Termine | `yfinance` ist nicht mit Yahoo verbunden. Die Yahoo-Bedingungen sehen persönliche, nicht-kommerzielle Nutzung vor. |
| Finnhub, Twelve Data, Alpha Vantage | Ersatz-Kursquellen | eigener API-Schlüssel nötig, jeweilige Bedingungen |
| RSS-Feeds (u. a. Bloomberg, Dow Jones/MarketWatch, Yahoo, NYT, Investopedia) | Schlagzeilen als KI-Kontext | Lizenzstatus siehe [`docs/NEWS-LICENSE-REVIEW.md`](docs/NEWS-LICENSE-REVIEW.md). Nur für private, interne Auswertung, keine Weiterverbreitung. |
| KI-Anbieter (u. a. OpenRouter, Nous, Zen und die dort angebotenen Modelle) | Entscheidungen, Bewertungen | eigene Zugänge, jeweilige Bedingungen und Modell-Lizenzen |
| ntfy.sh, Tailscale | Benachrichtigungen, Fernzugriff | optional, jeweilige Bedingungen |

## Marken

Genannte Produkt-, Börsen- und Firmennamen sowie Ticker-Symbole sind Marken bzw. Kennzeichen ihrer Inhaber. Ihre Nennung dient nur der Beschreibung. Es besteht keine Verbindung zu den genannten Unternehmen.

## Lizenzen

- **Lizenz dieses Projekts:** GNU Affero General Public License v3.0 oder später (AGPL-3.0-or-later), Copyright © 2026 Goldi5. Volltext in [`LICENSE`](LICENSE).
  - Erlaubt: nutzen, ändern, weitergeben, auch kommerziell.
  - Pflicht: Wer eine veränderte Fassung weitergibt oder Nutzern über ein Netzwerk zur Verfügung stellt, muss ihnen den vollständigen Quellcode dieser Fassung unter AGPL anbieten (§ 13). Urheber- und Lizenzhinweise bleiben erhalten.
  - Ohne Gewährleistung und Haftung (§§ 15, 16).
- Alle verwendeten Pakete stehen unter Lizenzen, die mit der AGPL-3.0 vereinbar sind (MIT, BSD, Apache-2.0, MPL-2.0, LGPL, PSF).
- Lizenzen der verwendeten Pakete: siehe [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md). Sie werden nicht mitgeliefert, sondern bei der Installation aus PyPI geladen.

*Diese Hinweise sind keine Rechtsberatung. Vor einer kommerziellen Nutzung sollten insbesondere die Datenlizenzen juristisch geprüft werden.*
