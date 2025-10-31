#!/bin/sh
set -e

# 🧹 Remove any preexisting default config files to prevent duplication
rm -f /etc/nginx/conf.d/*.conf
rm -f /docker-entrypoint.d/20-envsubst-on-templates.sh

# Ensure log file exists and writable
rm -f /var/log/nginx/access.log
touch /var/log/nginx/access.log
chmod 666 /var/log/nginx/access.log


# Configure upstreams dynamically
BLUE_CONFIG="backup"
GREEN_CONFIG="backup"

if [ "$ACTIVE_POOL" = "blue" ]; then
  BLUE_CONFIG="max_fails=1 fail_timeout=1s"
elif [ "$ACTIVE_POOL" = "green" ]; then
  GREEN_CONFIG="max_fails=10 fail_timeout=10s"
fi

UPSTREAM_SERVERS="server app_blue:$PORT $BLUE_CONFIG; server app_green:$PORT $GREEN_CONFIG;"
export UPSTREAM_SERVERS

# Render nginx config
envsubst '$UPSTREAM_SERVERS $PORT' \
  < /etc/nginx/templates/nginx.conf.template \
  > /etc/nginx/conf.d/default.conf

echo "--- Rendered Nginx Config ---"
cat /etc/nginx/conf.d/default.conf
echo "-----------------------------"

# Start nginx
exec nginx -g 'daemon off;'
