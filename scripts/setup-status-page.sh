#!/bin/bash
# Setup public status page at status.engramia.dev
# Prerequisites: nginx installed, DNS CNAME status.engramia.dev → <VPS IP>

set -euo pipefail

DOMAIN="status.engramia.dev"
EMAIL="${CERT_EMAIL:-ops@engramia.dev}"
NGINX_CONF_SRC="$(dirname "$0")/../nginx/status.engramia.dev.conf"
NGINX_CONF_DEST="/etc/nginx/sites-available/status.engramia.dev"

echo "=== Engramia Status Page Setup ==="
echo "Domain: $DOMAIN"
echo ""

# 1. Check nginx
if ! command -v nginx &>/dev/null; then
    echo "ERROR: nginx not installed. Run: apt install nginx"
    exit 1
fi

# 2. Copy nginx config (without SSL first for certbot)
cat > /tmp/status-temp.conf <<'EOF'
server {
    listen 80;
    server_name status.engramia.dev;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}
EOF

sudo cp /tmp/status-temp.conf "$NGINX_CONF_DEST"
sudo ln -sf "$NGINX_CONF_DEST" /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 3. Get certificate
if ! sudo certbot certificates 2>/dev/null | grep -q "$DOMAIN"; then
    echo "Getting Let's Encrypt certificate..."
    sudo certbot certonly --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive
else
    echo "Certificate already exists for $DOMAIN"
fi

# 4. Install full config with SSL
sudo cp "$NGINX_CONF_SRC" "$NGINX_CONF_DEST"
sudo nginx -t && sudo systemctl reload nginx

echo ""
echo "=== Nginx setup complete ==="
echo ""
echo "Next steps in Uptime Kuma UI (http://localhost:3001):"
echo "  1. Go to Status Pages → Add Status Page"
echo "  2. Name: 'Engramia Status'"
echo "  3. Slug: 'engramia' (URL will be /status/engramia)"
echo "  4. Domain: status.engramia.dev"
echo "  5. Add monitors: API Health, Database, LLM Provider"
echo "  6. Toggle 'Published' → ON"
echo "  7. Save"
echo ""
echo "DNS: Add CNAME status.engramia.dev → <your VPS IP>"
echo "Status page will be live at: https://status.engramia.dev"
