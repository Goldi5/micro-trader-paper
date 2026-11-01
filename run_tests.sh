#!/usr/bin/env bash
# run_tests.sh - Tests in einer Wegwerf-Kopie ausfuehren (nie im Live-Ordner).
#
#   ./run_tests.sh            Offline-Tests (kein Netz, keine Live-Daten noetig)
#   ./run_tests.sh alle       ALLE Tests, mit einer Kopie der aktuellen Live-Daten
#   ./run_tests.sh test_x.py  einzelne Tests aus tests/ (in der Kopie mit Live-Daten)
#
# Hintergrund: Einige Tests veraendern Dateien (z. B. config.json, Testdepots).
# Seit 01.11.2026 lesen alle Tests ihren Basisordner aus MT_BASE; dieses
# Skript setzt MT_BASE auf eine temporaere Kopie und loescht sie danach.
set -uo pipefail
QUELLE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

# Laufen ohne Netz und ohne Live-Daten in einem frischen Clone durch
# (gemessen am 01.11.2026). Diese Liste nutzt auch die GitHub-Action.
OFFLINE=(
  test_aktien_beta.py test_e2e_engine.py test_engine_buchung.py
  test_etf_deckel_luecke.py test_hebel_trennung.py test_hebelfilter.py
  test_imports.py test_keine_doppelausfuehrung.py test_leiter_sperre.py
  test_live_readiness.py test_menge_floor.py
  test_mtlog.py test_ops_center.py test_quiet_regression.py
  test_risk_regression.py test_server_security.py test_spec_deckel_kopplung.py
  test_sqli_regression.py test_tierignore.py test_timeseries.py
  test_trader_kursausfall.py test_wochenbericht_einmal.py test_handelskosten.py test_exits.py test_earnings.py test_bericht_kennzahlen.py test_watchdog_alarme.py test_handbuch.py
  test_xss_regression.py test_zusatz.py
)

MODUS="${1:-offline}"
KOPIE="$(mktemp -d /tmp/mt_tests.XXXXXX)"
trap 'rm -rf "$KOPIE"' EXIT

if [[ "$MODUS" == "offline" ]]; then
  # Nur versionierte Dateien = Zustand eines frischen Clones
  git -C "$QUELLE" archive HEAD | tar -x -C "$KOPIE"
  TESTS=("${OFFLINE[@]}")
else
  # Kompletter Ordner inkl. Laufzeitdaten, ohne venv/.git/Logs
  tar -C "$QUELLE" --exclude=./venv --exclude=./.git --exclude=./logs \
      --exclude='*.log*' -cf - . | tar -x -C "$KOPIE"
  if [[ "$MODUS" == "alle" ]]; then
    mapfile -t TESTS < <(cd "$KOPIE/tests" && ls test_*.py)
  else
    TESTS=("$@")
  fi
fi

# venv der Quelle verwenden (manche Tests starten venv/bin/python)
if [[ -d "$QUELLE/venv" ]]; then
  ln -s "$QUELLE/venv" "$KOPIE/venv"
  PY="$KOPIE/venv/bin/python"
else
  # Ohne venv (z. B. GitHub Actions): venv/bin/python als Verweis auf das
  # vorhandene Python, weil einige Tests genau diesen Pfad starten.
  PY="$(command -v "${PYTHON:-python3}")"
  mkdir -p "$KOPIE/venv/bin"
  ln -s "$PY" "$KOPIE/venv/bin/python"
fi

export MT_BASE="$KOPIE"
ok=0; fehl=0; FEHLGESCHLAGEN=()
for t in "${TESTS[@]}"; do
  if (cd "$KOPIE" && timeout 180 "$PY" "tests/$t" >"$KOPIE/.log_$t" 2>&1); then
    printf "  OK    %s\n" "$t"; ok=$((ok+1))
  else
    printf "  FEHL  %s\n" "$t"; fehl=$((fehl+1)); FEHLGESCHLAGEN+=("$t")
    tail -n 5 "$KOPIE/.log_$t" | sed 's/^/          /'
  fi
done
echo
echo "Ergebnis: $ok bestanden, $fehl fehlgeschlagen (Modus: $MODUS)"
[[ $fehl -eq 0 ]]
