#!/usr/bin/env bash
# Lanceur quotidien Linux / Unraid.
set -euo pipefail

fail() { printf 'Erreur : %s\n' "$*" >&2; exit 2; }
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
[[ -f main.py && -f requirements.txt ]] || fail 'main.py ou requirements.txt introuvable.'

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || fail 'Python 3.11+ introuvable. Installer Python ou définir PYTHON.'
"$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail 'Python 3.11 minimum requis.'

if [[ ! -x .venv/bin/python ]]; then
    printf 'Création de l’environnement Python .venv…\n'
    "$PYTHON" -m venv .venv || fail 'Création impossible : vérifier le module venv/ensurepip et les droits du dossier.'
fi
VENV_PYTHON="$PWD/.venv/bin/python"
"$VENV_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || fail 'Le Python de .venv est trop ancien. Recréer .venv avec Python 3.11+.'
"$VENV_PYTHON" -m pip --version >/dev/null 2>&1 || fail 'pip manque dans .venv. Recréer cet environnement avec venv/ensurepip disponible.'

# Ne solliciter le réseau que si les dépendances doivent être installées/réparées.
if ! cmp -s requirements.txt .venv/requirements.installed.txt \
    || ! "$VENV_PYTHON" -c 'import plexapi, requests, yaml, filelock, tzdata' >/dev/null 2>&1 \
    || ! "$VENV_PYTHON" -m pip check >/dev/null 2>&1; then
    printf 'Installation / vérification des dépendances…\n'
    "$VENV_PYTHON" -m pip install -r requirements.txt || fail 'Installation impossible : vérifier le réseau et les droits de .venv.'
    "$VENV_PYTHON" -m pip check || fail 'Dépendances incompatibles dans .venv.'
    cp -- requirements.txt .venv/requirements.installed.txt
fi

# Le programme valide le YAML, les accès Plex et la base, sans exposer les secrets.
# --run-once évite de rester en attente du planificateur interne.
printf 'Lancement de la Sélection du Moment (cycle unique)…\n'
exec "$VENV_PYTHON" main.py --run-once "$@"
