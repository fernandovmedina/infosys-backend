#!/usr/bin/env bash
# Share application data (users, runs, fraud results) between machines.
#
#   scripts/snapshot.sh export [file]   # default: snapshot/infosys-snapshot.tar.gz
#   scripts/snapshot.sh import <file>
#
# The snapshot holds a data-only pg_dump of the app tables plus the run dataset
# files that investigation_run rows point at; one without the other is broken.
# Excluded: the SAT listing (re-seeded from black_list.csv on first start) and
# auth sessions (sign in again).
#
# Run dataset files are read from / written to the `api` container's volume when
# it is running, otherwise the host's storage/runs (local `uvicorn` setup).
#
# The snapshot contains password hashes and uploaded datasets: share it
# privately, don't commit it (snapshot/ is gitignored).
set -euo pipefail

cd "$(dirname "$0")/.."

TABLES=(app_user investigation_run fraud_analysis fraud_signal run_event)
psql_db() { docker compose exec -T postgres psql -U infosys -d infosys -v ON_ERROR_STOP=1 "$@"; }
api_running() { [ -n "$(docker compose ps --status running -q api 2>/dev/null)" ]; }

export_snapshot() {
    local out=${1:-snapshot/infosys-snapshot.tar.gz}
    local tmp
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT

    echo "==> Dumping ${TABLES[*]}"
    docker compose exec -T postgres pg_dump -U infosys -d infosys \
        --data-only --no-owner --no-privileges "${TABLES[@]/#/--table=}" >"$tmp/data.sql"

    mkdir -p "$tmp/runs"
    if api_running; then
        echo "==> Copying run datasets from the api container"
        docker compose exec -T api tar -C /app/storage/runs -cf - . | tar -C "$tmp/runs" -xf -
    elif [ -d storage/runs ]; then
        echo "==> Copying run datasets from storage/runs"
        cp -R storage/runs/. "$tmp/runs/"
    fi

    mkdir -p "$(dirname "$out")"
    tar -C "$tmp" -czf "$out" data.sql runs
    echo "==> Wrote $out"
}

import_snapshot() {
    local in=${1:?usage: scripts/snapshot.sh import <file>}
    local tmp
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    tar -C "$tmp" -xzf "$in"

    if ! psql_db -Atc "SELECT to_regclass('run_event') IS NOT NULL" | grep -q t; then
        echo "Schema is missing: start the stack first (docker compose up -d)." >&2
        exit 1
    fi

    echo "==> Replacing ${TABLES[*]} (existing rows are deleted)"
    {
        echo "BEGIN;"
        # Rows arrive in dump order; skip FK triggers until the load is complete.
        echo "SET session_replication_role = replica;"
        echo "TRUNCATE $(IFS=,; echo "${TABLES[*]}") CASCADE;"
        cat "$tmp/data.sql"
        echo "COMMIT;"
    } | psql_db -q >/dev/null

    echo "==> Restoring run datasets"
    if api_running; then
        tar -C "$tmp/runs" -cf - . | docker compose exec -T api tar -C /app/storage/runs -xf -
    else
        mkdir -p storage/runs
        cp -R "$tmp/runs/." storage/runs/
    fi
    echo "==> Imported $in"
}

case "${1:-}" in
    export) shift; export_snapshot "$@" ;;
    import) shift; import_snapshot "$@" ;;
    *) sed -n '2,6p' "$0"; exit 2 ;;
esac
