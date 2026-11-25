#!bin/bash
set -e

# /cache is owned by the host user (uid 1001), container runs as frappe (uid 1000)
git config --global --add safe.directory '*' || true

# Use fast CN mirrors (container has no access to the host proxy)
npm config set registry https://registry.npmmirror.com
yarn config set registry https://registry.npmmirror.com
pip config set global.index-url https://mirrors.cernet.edu.cn/pypi/web/simple

# GitHub is unreachable from this container (TLS reset), so frappe's git-based
# dependencies are resolved from local clones mounted at /cache
git config --global url."file:///cache/pypika".insteadOf "https://github.com/frappe/pypika"
git config --global url."file:///cache/gunicorn".insteadOf "https://github.com/frappe/gunicorn"

export PATH="${NVM_DIR}/versions/node/v${NODE_VERSION_DEVELOP}/bin/:${PATH}"

BENCH_DIR=/home/frappe/frappe-bench

# Phase 1: build the bench (apps + common site config). Skipped when it is already there.
if [ ! -d "$BENCH_DIR/apps/frappe" ] || [ ! -f "$BENCH_DIR/sites/apps.txt" ]; then
    # Drop a half-built bench left behind by a failed run
    if [ -d "$BENCH_DIR" ]; then
        echo "Incomplete bench found, removing it..."
        rm -rf "$BENCH_DIR"
    fi

    echo "Creating new bench..."

    bench init --skip-redis-config-generation --frappe-path /cache/frappe frappe-bench

    cd "$BENCH_DIR"

    # Use containers instead of localhost
    bench set-mariadb-host mariadb
    bench set-redis-cache-host redis://redis:6379
    bench set-redis-queue-host redis://redis:6379
    bench set-redis-socketio-host redis://redis:6379

    # Remove redis, watch from Procfile
    sed -i '/redis/d' ./Procfile
    sed -i '/watch/d' ./Procfile

    bench get-app erpnext /cache/erpnext
    bench get-app hrms /cache/hrms
else
    echo "Bench already exists, skipping init"
    cd "$BENCH_DIR"
fi

# Phase 2: create the site and install the apps.
site_db_exists() {
    local conf="$BENCH_DIR/sites/hrms.localhost/site_config.json"
    [ -f "$conf" ] || return 1
    local db
    db=$(sed -n 's/.*"db_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$conf")
    [ -n "$db" ] || return 1
    mariadb -h mariadb -uroot -p123 -N -e "SHOW DATABASES LIKE '$db'" 2>/dev/null | grep -q . || return 1
    # a database created by an interrupted `bench new-site` has no frappe tables yet
    mariadb -h mariadb -uroot -p123 -N -D "$db" -e "SHOW TABLES LIKE 'tabSingles'" 2>/dev/null | grep -q .
}

if ! site_db_exists; then
    echo "Creating site hrms.localhost..."
    rm -rf "$BENCH_DIR/sites/hrms.localhost"
    bench new-site hrms.localhost \
    --force \
    --mariadb-root-password 123 \
    --admin-password admin \
    --no-mariadb-socket

    bench --site hrms.localhost set-config developer_mode 1
    bench --site hrms.localhost enable-scheduler
    bench use hrms.localhost
else
    echo "Site hrms.localhost already exists, skipping site setup"
fi

# Idempotent: prints "App hrms already installed" when it is
bench --site hrms.localhost install-app hrms

# Apply Employee form display settings on every container start.
bench --site hrms.localhost execute "exec(open('/workspace/ensure_employee_form_customizations.py').read(), globals())"
bench --site hrms.localhost clear-cache

exec bench start
