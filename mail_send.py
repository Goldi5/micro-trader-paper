#!/usr/bin/env python3
"""Versand der Tagesberichte per E-Mail (SMTP, 1&1/IONOS).

Zugangsdaten kommen aus der .env des Projekts (gitignored, 0600):

    SMTP_HOST=smtp.1und1.de
    SMTP_PORT=587
    SMTP_USER=name@example.de
    SMTP_PASS=...
    SMTP_TO=name@example.de      (optional, Standard: SMTP_USER)

Die Datei .env wird NIE geloggt. Fehlt eine Angabe, wird der Versand
als Fehler gemeldet (nicht stillschweigend uebersprungen) - sonst
sieht ein nicht konfigurierter Versand aus wie ein erfolgreicher.

Nutzung als Modul:
    from mail_send import sende_bericht
    ok, meldung = sende_bericht("/opt/micro-trader/reports/x.pdf")

Nutzung als CLI (Test):
    python3 mail_send.py /pfad/zum.pdf
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV_DATEI = BASE / ".env"

# Erwartete Schluessel und ihre Standardwerte
DEFAULTS = {
    "SMTP_HOST": "smtp.1und1.de",
    "SMTP_PORT": "587",
    "SMTP_USER": "",
    "SMTP_PASS": "",
    "SMTP_TO": "",  # leer -> SMTP_USER (keine Adresse im Code, 01.11.2026)
}


def _lies_env(pfad: Path = ENV_DATEI) -> dict:
    """Liest die .env als einfache KEY=VALUE-Datei. Keine Expansion,
    keine Kommentar-Tricks - nur die Zeilen, die wie Zuweisungen aussehen."""
    werte = dict(DEFAULTS)
    if not pfad.exists():
        return werte
    for roh in pfad.read_text(encoding="utf-8", errors="replace").splitlines():
        zeile = roh.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, _, wert = zeile.partition("=")
        schluessel = schluessel.strip()
        if schluessel in werte:
            # Anfuehrungszeichen entfernen, falls vorhanden
            werte[schluessel] = wert.strip().strip('"').strip("'")
    return werte


def konfiguriert() -> tuple[bool, str]:
    """Prueft, ob die noetigen SMTP-Werte gesetzt sind. Gibt (ok, meldung)."""
    w = _lies_env()
    if not w.get("SMTP_TO"):
        w["SMTP_TO"] = w.get("SMTP_USER", "")
    fehlend = [k for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_TO")
               if not w.get(k)]
    if fehlend:
        return False, "SMTP nicht konfiguriert, es fehlen: " + ", ".join(fehlend)
    return True, "ok"


def _maskiere(wert: str) -> str:
    """Nur fuer Logs: zeigt Laenge, nie den Inhalt."""
    if not wert:
        return "(leer)"
    return f"({len(wert)} Zeichen)"


def sende_bericht(pdf_pfad: str | os.PathLike,
                  betreff: str | None = None,
                  empfaenger: str | None = None,
                  text: str | None = None) -> tuple[bool, str]:
    """Sendet eine PDF-Datei als Anhang. Gibt (erfolg, meldung) zurueck.

    Die Meldung enthaelt NIE das Passwort und NIE die SMTP_USER-Adresse
    in Klartextform jenseits der ohnehin sichtbaren Empfaengeradresse.
    """
    pdf = Path(pdf_pfad)
    if not pdf.exists():
        return False, f"PDF nicht gefunden: {pdf}"

    w = _lies_env()
    ok, meldung = konfiguriert()
    if not ok:
        return False, meldung

    host = w["SMTP_HOST"]
    port = int(w["SMTP_PORT"])
    user = w["SMTP_USER"]
    pw = w["SMTP_PASS"]
    an = empfaenger or w["SMTP_TO"]

    betreff = betreff or f"Micro-Trader Tagesbericht {pdf.stem}"

    msg = EmailMessage()
    msg["Subject"] = betreff
    msg["From"] = user
    msg["To"] = an
    import re as _re
    _datum = pdf.stem.split("_")[1] if "_" in pdf.stem else pdf.stem
    # Datum aus "daily_report_2026-10-14_v2.58.7_..." extrahieren
    _m = _re.search(r"(\d{4}-\d{2}-\d{2})", pdf.stem)
    if _m:
        _datum = _m.group(1)
    msg.set_content(text or (
        f"Micro-Trader Tagesbericht {_datum}\n\n"
        "Anbei der vollstaendige Bericht als PDF.\n"
        "Die Kernzahlen (Gesamtwert, Rendite, Trades) stehen direkt im PDF.\n"
    ))
    msg.add_attachment(
        pdf.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=pdf.name,
    )

    try:
        with smtplib.SMTP(host, port, timeout=45) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(user, pw)
            s.send_message(msg)
        return True, f"E-Mail an {an} gesendet ({pdf.name}, {pdf.stat().st_size} Bytes)"
    except smtplib.SMTPAuthenticationError as e:
        return False, f"SMTP-Login fehlgeschlagen ({e.smtp_code}); Zugangsdaten pruefen"
    except smtplib.SMTPException as e:
        return False, f"SMTP-Fehler: {type(e).__name__}: {str(e)[:160]}"
    except (OSError, ssl.SSLError) as e:
        return False, f"Netzwerk/TLS-Fehler: {type(e).__name__}: {str(e)[:160]}"


def main() -> int:
    if len(sys.argv) < 2:
        print("Nutzung: python3 mail_send.py <pdf-pfad> [empfaenger]")
        print("Status:", konfiguriert()[1])
        return 2
    an = sys.argv[2] if len(sys.argv) > 2 else None
    ok, meldung = sende_bericht(sys.argv[1], empfaenger=an)
    print(("OK   " if ok else "FEHL ") + meldung)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
