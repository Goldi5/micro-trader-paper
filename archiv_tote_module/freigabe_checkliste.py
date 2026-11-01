"""freigabe_checkliste.py — Phase 14: Manueller Live-Freigabeprozess.

Druckt die Checkliste fuer die manuelle Live-Freigabe (Vier-Augen + MFA).
KEINE automatische Aktivierung. Nur als Entscheidungshilfe.

Aufruf: python freigabe_checkliste.py
"""

CHECKLISTE = [
    ("P0-Blocker", "markt_daten persistiert (Phase 1)"),
    ("P0-Blocker", "News fliesst in Trading-Kontext (Phase 5)"),
    ("Sicherheit", "CSRF vollstaendig verdrahtet (Phase 1 P2)"),
    ("Sicherheit", "MFA fuer ALLE Admins aktiv (Phase 1 P3)"),
    ("Sicherheit", "Tenant-Isolation getestet (Phase 1 P4)"),
    ("Live-System", "live_system.py isoliert, liest KEINE Paper-Depots (Phase 7)"),
    ("Live-System", "ReleaseRegistry + live_releases Tabelle (Phase 8)"),
    ("Live-System", "BrokerSimulator ohne echte Orders (Phase 9)"),
    ("Live-System", "Reconciliation funktioniert (Phase 10)"),
    ("Live-System", "Kill-Switch + Monitoring-Routen (Phase 11)"),
    ("Live-System", "Live-Readiness-Tests PASS (Phase 12)"),
    ("Live-System", "Micro-Live vorbereitet: 1 Portfolio, harte Limits (Phase 13)"),
    ("Freigabe", "Release hash registriert + APPROVED (Vier-Augen, MFA)"),
    ("Freigabe", "Broker-Adapter nur Sandbox/Simulator (kein Echtgeld)"),
    ("Freigabe", "Kill-Switch manuell testbar (Dashboard /api/live_kill_switch)"),
    ("Monitoring", "Live-Status sichtbar (Dashboard /api/live_status)"),
    ("Notfall", "Rollback-Prozess dokumentiert"),
]


def main():
    print("=== PHASE 14: Manueller Live-Freigabeprozess ===\n")
    print("VORaussetzung: ALLE Punkte muessen mit [X] bestaetigt sein.")
    print("Freigabe NUR durch Benutzer (nicht automatisch durch Agent).\n")
    for kategorie, punkt in CHECKLISTE:
        print(f"  [ ] {kategorie:12} {punkt}")
    print("\nNach Bestaetigung aller Punkte:")
    print("  1. LiveSystem.aktiv = True NUR manuell setzen (nicht durch Agent)")
    print("  2. Release ueber ReleaseRegistry.approve() mit MFA + Vier-Augen")
    print("  3. Kill-Switch vorher als Funktion testen")
    print("  4. Start mit 1 Micro-Live-Portfolio (100 EUR Cap)")


if __name__ == "__main__":
    main()
