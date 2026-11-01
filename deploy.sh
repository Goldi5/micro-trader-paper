#!/usr/bin/env bash
# deploy.sh - neuen Stand von GitHub (main) auf dem Server einspielen.
#
# Ablauf: holen -> anzeigen -> nachfragen -> fast-forward -> pruefen
#         -> Dienste neu starten -> Status.
# Es wird nie etwas ueberschrieben: lokale Aenderungen, die mit dem neuen
# Stand kollidieren, lassen das Update abbrechen (git merge --ff-only).
#
# Aufruf:  cd /opt/micro-trader && ./deploy.sh        (mit Rueckfrage)
#                 ./deploy.sh -y                              (ohne Rueckfrage)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

JA=0; [[ "${1:-}" == "-y" ]] && JA=1
DIENSTE=(micro-trader mt-scheduler)
PY=venv/bin/python
PIP=venv/bin/pip

echo "== Hole Stand von GitHub ..."
git fetch origin main
ALT=$(git rev-parse HEAD)
NEU=$(git rev-parse origin/main)

if [[ "$ALT" == "$NEU" ]]; then
  echo "Schon aktuell ($(git log --oneline -1))."
  exit 0
fi
if ! git merge-base --is-ancestor "$ALT" "$NEU"; then
  echo "ABBRUCH: Lokal gibt es Commits, die nicht auf GitHub sind."
  echo "Erst pushen:  git push origin main"
  exit 1
fi

echo
echo "== Neue Commits:"
git log --oneline "$ALT..$NEU"
echo
echo "== Geaenderte Dateien:"
git diff --stat "$ALT" "$NEU" | tail -n 25
echo

if [[ $JA -eq 0 ]]; then
  read -r -p "Einspielen und Dienste neu starten? [j/N] " a
  [[ "$a" =~ ^[jJyY]$ ]] || { echo "Abgebrochen, nichts geaendert."; exit 0; }
fi

# Dateien, die das Update aus Git entfernt (z. B. Laufzeitdaten, die
# kuenftig git-ignoriert sind), wuerde git beim Merge LOESCHEN. Sie werden
# vorher gesichert und danach wieder hingelegt - der Inhalt bleibt.
SICHERUNG="${MT_DEPLOY_SICHERUNG:-$HOME/mt-deploy-sicherung}/$(date +%Y%m%d-%H%M%S)"
mapfile -t ENTFERNT < <(git diff --diff-filter=D --name-only "$ALT" "$NEU")
for f in "${ENTFERNT[@]}"; do
  [[ -f "$f" ]] || continue
  mkdir -p "$SICHERUNG/$(dirname "$f")"
  cp -p "$f" "$SICHERUNG/$f"
done
if [[ ${#ENTFERNT[@]} -gt 0 ]]; then
  echo "== ${#ENTFERNT[@]} Datei(en) verlassen Git - gesichert in $SICHERUNG"
  # lokale Aenderungen daran wuerden den Merge blockieren (Inhalt ist gesichert)
  git checkout -- "${ENTFERNT[@]}" 2>/dev/null || true
fi

echo "== Spiele ein ..."
git merge --ff-only origin/main

for f in "${ENTFERNT[@]}"; do
  if [[ -f "$SICHERUNG/$f" && ! -e "$f" ]]; then
    mkdir -p "$(dirname "$f")"
    cp -p "$SICHERUNG/$f" "$f"
  fi
done
if [[ ${#ENTFERNT[@]} -gt 0 ]]; then
  echo "== Laufzeitdateien wiederhergestellt (jetzt git-ignoriert)"
fi

GEAENDERT=$(git diff --name-only "$ALT" HEAD)

if grep -qx requirements.txt <<<"$GEAENDERT"; then
  echo "== requirements.txt geaendert -> installiere Pakete ..."
  "$PIP" install -q -r requirements.txt
fi

echo "== Pruefe Syntax ..."
FEHLER=0
while read -r f; do
  [[ "$f" == *.py && -f "$f" ]] || continue
  "$PY" -m py_compile "$f" || FEHLER=1
done <<<"$GEAENDERT"

# Offline-Tests in einer Wegwerf-Kopie (run_tests.sh) - fassen keine
# Live-Daten an und brauchen kein Netz.
echo "== Offline-Tests (Kopie in /tmp) ..."
if [[ -x ./run_tests.sh ]]; then
  if ./run_tests.sh >/tmp/deploy_tests.log 2>&1; then
    echo "   $(tail -n 1 /tmp/deploy_tests.log)"
  else
    grep -E "FEHL|Ergebnis" /tmp/deploy_tests.log | sed 's/^/   /'
    echo "   (vollstaendiges Log: /tmp/deploy_tests.log)"
    FEHLER=1
  fi
fi

if [[ $FEHLER -ne 0 ]]; then
  echo
  echo "ABBRUCH vor dem Neustart: Pruefung fehlgeschlagen. Die Dienste laufen"
  echo "weiter mit dem alten Code im Speicher. Zurueck auf den alten Stand:"
  echo "   git reset --keep $ALT"
  exit 1
fi

# Handbuch-PDF lokal erneuern (docs/handbuch/Micro-Trader-Handbuch.pdf).
# Fehler hier halten das Update nicht auf.
if [[ -f tools/handbuch_pdf.py ]]; then
  if "$PY" tools/handbuch_pdf.py >/tmp/deploy_handbuch.log 2>&1; then
    echo "== Handbuch-PDF aktualisiert: docs/handbuch/Micro-Trader-Handbuch.pdf"
  else
    echo "   (Handbuch-PDF nicht erzeugt, siehe /tmp/deploy_handbuch.log)"
  fi
fi

if grep -q '^proxy/' <<<"$GEAENDERT"; then
  DIENSTE+=(micro-trader-proxy)
fi

echo "== Starte neu: ${DIENSTE[*]}"
systemctl restart "${DIENSTE[@]}"
sleep 3
for d in "${DIENSTE[@]}"; do
  printf "   %-22s %s\n" "$d" "$(systemctl is-active "$d")"
done
echo
echo "Fertig: $(git log --oneline -1)"
