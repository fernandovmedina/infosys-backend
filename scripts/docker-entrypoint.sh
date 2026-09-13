#!/bin/sh
# Container entrypoint: bring the database up to date, then run the API.
#
# database.sql and alter.sql are idempotent, so they run on every start and new
# migrations are picked up automatically. The SAT listing is imported only when
# its table is still empty.
set -eu

: "${DATABASE_URL:?DATABASE_URL must be set}"

echo "==> Waiting for PostgreSQL"
tries=0
until pg_isready -q -d "$DATABASE_URL"; do
    tries=$((tries + 1))
    if [ "$tries" -ge 30 ]; then
        echo "PostgreSQL is not reachable at \$DATABASE_URL" >&2
        exit 1
    fi
    sleep 1
done

echo "==> Applying schema and migrations"
psql "$DATABASE_URL" -q -v ON_ERROR_STOP=1 -f database/database.sql -f database/alter.sql

seeded=$(psql "$DATABASE_URL" -Atc "SELECT EXISTS (SELECT 1 FROM sat_blacklist_record)")
if [ "$seeded" != "t" ]; then
    echo "==> Seeding SAT blacklist from black_list.csv"
    sat-blacklist-import
    psql "$DATABASE_URL" -q -c "ANALYZE sat_blacklist_record"
fi

exec "$@"
