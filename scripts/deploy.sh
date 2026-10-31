#!/bin/sh
# Déploie un commit de main sur le serveur. Appelé par GitHub Actions via une clé SSH
# dont la commande est forcée dans authorized_keys : le SHA arrive dans SSH_ORIGINAL_COMMAND.
# Utilisable à la main : scripts/deploy.sh <sha>
set -eu

main() {
    sha=${SSH_ORIGINAL_COMMAND:-${1:-}}
    case $sha in
        *[!0-9a-f]* | '') echo "SHA invalide : 40 caractères hexadécimaux attendus." >&2; exit 2 ;;
    esac
    [ ${#sha} -eq 40 ] || { echo "SHA invalide : 40 caractères hexadécimaux attendus." >&2; exit 2; }

    cd "$(dirname "$0")/.."
    exec 9>"${TMPDIR:-/tmp}/observatoire-deploy.lock"
    flock 9

    git fetch --quiet origin main
    git merge-base --is-ancestor "$sha" origin/main || { echo "Commit absent de main : $sha" >&2; exit 2; }
    git checkout --quiet --detach "$sha"

    python3 scripts/init_env.py
    if [ -n "$(docker compose ps --status running -q db)" ]; then
        python3 scripts/backup.py
        # Images make dumps large: only the seven most recent are kept.
        ls -1t backups/observatoire-*.dump | tail -n +8 | xargs -r rm --
    fi
    docker compose up -d --build --remove-orphans --wait --wait-timeout 300
    docker image prune -f >/dev/null
    echo "Déployé : $(git log --oneline -1)"
}

main "$@"
