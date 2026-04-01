#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# destroy.sh — Tear down the IBKR Webhook Relay infrastructure
# ---------------------------------------------------------------------------

# Load .env for DO token
if [[ ! -f .env ]]; then
  echo "Error: .env file not found." >&2
  exit 1
fi

set -a
source .env
set +a

if [[ -z "${DO_API_TOKEN:-}" ]]; then
  echo "Error: DO_API_TOKEN is not set in .env" >&2
  exit 1
fi

export TF_VAR_do_token="$DO_API_TOKEN"
# Terraform needs all required variables even for destroy
export TF_VAR_tws_userid="${TWS_USERID:-placeholder}"
export TF_VAR_tws_password="${TWS_PASSWORD:-placeholder}"
export TF_VAR_vnc_password="${VNC_SERVER_PASSWORD:-placeholder}"
export TF_VAR_webhook_url="${TARGET_WEBHOOK_URL:-placeholder}"
export TF_VAR_webhook_secret="${WEBHOOK_SECRET:-placeholder}"

cd terraform
terraform destroy -auto-approve -input=false

echo ""
echo "Infrastructure destroyed."
