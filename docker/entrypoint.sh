#!/bin/sh
set -e

# RUN_MIGRATIONS=0 for extra containers of the same image (workers) so only one runs migrations
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py collectstatic --noinput --verbosity 0
fi

exec "$@"
