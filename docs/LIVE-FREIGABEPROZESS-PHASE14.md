# LIVE-FREIGABEPROZESS — Phase 14

> Phase 14: Manueller Live-Freigabeprozess. Stand: 2026-08-12.

## Prinzip

Keine automatische Live-Aktivierung durch den Agent. Freigabe NUR durch Benutzer
(Vier-Augen + MFA). `freigabe_checkliste.py` druckt die Entscheidungshilfe.

## Flow (Auftrag §Freigabemodell)

```text
Learning/Paper → Rule Candidate → Validation → Review → Approval
→ Signed/Hashed Release → Live-Release-Gate → Live-System
```

## Checkliste (Kurzform)

- [ ] P0-Blocker: markt_daten persistiert, News in Trading-Kontext
- [ ] Sicherheit: CSRF verdrahtet, MFA alle Admins, Tenant-Isolation getestet
- [ ] Live-System: isoliert (kein Paper-Lesen), ReleaseRegistry, BrokerSim (kein Echtgeld)
- [ ] Live-System: Reconciliation, Kill-Switch + Monitoring, Readiness-Tests PASS
- [ ] Live-System: Micro-Live vorbereitet (1 Portfolio, harte Limits)
- [ ] Freigabe: Release APPROVED (Vier-Augen, MFA), nur Sandbox/Simulator
- [ ] Notfall: Kill-Switch testbar, Rollback dokumentiert

## Aktivierung (manuell, NICHT durch Agent)

1. `LiveSystem.aktiv = True` nur durch Benutzer setzen
2. Release über `ReleaseRegistry.approve()` mit MFA
3. Kill-Switch vorher funktional testen
4. Start: 1 Micro-Live-Portfolio (100 EUR Cap)

## Status

Alle Phasen 0-14 implementiert + verifiziert (PAPER_ONLY). Live-Aktivierung
wartet auf manuelle Freigabe durch Benutzer (Phase 14).
