#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# deploy.sh — One-script deployment for IBKR Webhook Relay
# ---------------------------------------------------------------------------

# Check prerequisites
for cmd in terraform curl; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "Error: '$cmd' is required but not installed." >&2
    exit 1
  fi
done

# Load .env
if [[ ! -f .env ]]; then
  echo "Error: .env file not found. Copy .env.example to .env and fill in your values." >&2
  exit 1
fi

set -a
source .env
set +a

# Validate required variables
REQUIRED_VARS=(DO_API_TOKEN TWS_USERID TWS_PASSWORD VNC_SERVER_PASSWORD WEBHOOK_SECRET IBKR_FLEX_TOKEN IBKR_FLEX_QUERY_ID)
for var in "${REQUIRED_VARS[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "Error: $var is not set in .env" >&2
    exit 1
  fi
done

# Export as TF_VAR_ for Terraform
export TF_VAR_do_token="$DO_API_TOKEN"
export TF_VAR_tws_userid="$TWS_USERID"
export TF_VAR_tws_password="$TWS_PASSWORD"
export TF_VAR_trading_mode="${TRADING_MODE:-paper}"
export TF_VAR_vnc_password="$VNC_SERVER_PASSWORD"
export TF_VAR_webhook_url="${TARGET_WEBHOOK_URL:-}"
export TF_VAR_webhook_secret="$WEBHOOK_SECRET"
export TF_VAR_flex_token="$IBKR_FLEX_TOKEN"
export TF_VAR_flex_query_id="$IBKR_FLEX_QUERY_ID"
export TF_VAR_poll_interval="${POLL_INTERVAL_SECONDS:-600}"
export TF_VAR_time_zone="${TIME_ZONE:-America/New_York}"
export TF_VAR_java_heap_size="${JAVA_HEAP_SIZE:-768}"

# Run Terraform
cd terraform
terraform init -input=false
terraform apply -auto-approve -input=false

# Display results
DROPLET_IP=$(terraform output -raw droplet_ip)
VNC_URL=$(terraform output -raw vnc_url)

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "============================================"
echo ""
echo "  Droplet IP:  $DROPLET_IP"
echo "  VNC URL:     $VNC_URL"
echo ""
echo "  Next steps:"
echo "  1. Open the VNC URL in your browser"
echo "  2. Complete the IBKR 2FA handshake"
echo "  3. The relay will start listening for order fills"
echo ""
echo "  To SSH into the droplet:"
echo "    terraform output -raw ssh_private_key > ~/.ssh/ibkr-relay"
echo "    chmod 600 ~/.ssh/ibkr-relay"
echo "    ssh -i ~/.ssh/ibkr-relay root@$DROPLET_IP"
echo ""
echo "  To tear down:  ./destroy.sh"
echo "============================================"
