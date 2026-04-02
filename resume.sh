#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# resume.sh — Recreate the droplet from the paused snapshot and reassign
#              the reserved IP. Reads state from .pause-state.
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE_FILE="$SCRIPT_DIR/.pause-state"

if [[ ! -f "$STATE_FILE" ]]; then
  echo "Error: .pause-state not found — nothing to resume."
  echo "Run ./pause.sh first to create a snapshot."
  exit 1
fi

# Load .env and pause state
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "Error: .env file not found." >&2
  exit 1
fi
set -a; source "$SCRIPT_DIR/.env"; set +a
source "$STATE_FILE"

DO_TOKEN="${DO_API_TOKEN:?Set DO_API_TOKEN in .env}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ibkr-relay}"
API="https://api.digitalocean.com/v2"
AUTH="Authorization: Bearer $DO_TOKEN"

echo "Resuming from snapshot: $SNAPSHOT_NAME ($SNAPSHOT_ID)"
echo "  Region: $DROPLET_REGION"
echo "  Reserved IP: $RESERVED_IP"

# Select droplet size based on JAVA_HEAP_SIZE
_HEAP="${JAVA_HEAP_SIZE:-768}"
if   [[ "$_HEAP" -le 1024 ]]; then DROPLET_SIZE="s-1vcpu-2gb"
elif [[ "$_HEAP" -le 3072 ]]; then DROPLET_SIZE="s-2vcpu-4gb"
elif [[ "$_HEAP" -le 6144 ]]; then DROPLET_SIZE="s-4vcpu-8gb"
else                               DROPLET_SIZE="s-8vcpu-16gb"
fi
echo "  Droplet size: $DROPLET_SIZE (heap ${_HEAP}MB)"

# ---------------------------------------------------------------------------
# 1. Find the SSH key ID on DigitalOcean
# ---------------------------------------------------------------------------
echo "Looking up SSH key..."
SSH_KEY_ID=$(curl -s -H "$AUTH" "$API/account/keys" \
  | python3 -c "
import json, sys
keys = json.load(sys.stdin)['ssh_keys']
match = [k for k in keys if 'ibkr-relay' in k['name'].lower()]
print(match[0]['id'] if match else '')
")

SSH_KEYS_PARAM="[]"
if [[ -n "$SSH_KEY_ID" ]]; then
  SSH_KEYS_PARAM="[$SSH_KEY_ID]"
  echo "  SSH key ID: $SSH_KEY_ID"
else
  echo "  Warning: No 'ibkr-relay' SSH key found on DigitalOcean."
  echo "  You may need to add your SSH key manually after creation."
fi

# ---------------------------------------------------------------------------
# 2. Create droplet from snapshot
# ---------------------------------------------------------------------------
echo "Creating droplet from snapshot..."
DROPLET_ID=$(curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$API/droplets" \
  -d "{
    \"name\": \"ibkr-relay\",
    \"region\": \"$DROPLET_REGION\",
    \"size\": \"$DROPLET_SIZE\",
    \"image\": $SNAPSHOT_ID,
    \"ssh_keys\": $SSH_KEYS_PARAM
  }" | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['id'])")

if [[ -z "$DROPLET_ID" ]]; then
  echo "Error: Failed to create droplet."
  exit 1
fi
echo "  Droplet ID: $DROPLET_ID"

# Wait for droplet to become active
echo "  Waiting for droplet to boot..."
for i in $(seq 1 60); do
  STATUS=$(curl -s -H "$AUTH" "$API/droplets/$DROPLET_ID" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['droplet']['status'])")
  if [[ "$STATUS" == "active" ]]; then
    break
  fi
  sleep 3
done

if [[ "$STATUS" != "active" ]]; then
  echo "Error: Droplet did not become active in time."
  exit 1
fi
echo "  Droplet is active."

# ---------------------------------------------------------------------------
# 3. Assign the reserved IP to the new droplet
# ---------------------------------------------------------------------------
echo "Assigning reserved IP $RESERVED_IP..."
curl -s -X POST -H "$AUTH" -H "Content-Type: application/json" \
  "$API/reserved_ips/$RESERVED_IP/actions" \
  -d "{\"type\":\"assign\",\"droplet_id\":$DROPLET_ID}" > /dev/null
sleep 5

# ---------------------------------------------------------------------------
# 4. Push current .env and restart stack (in case .env changed while paused)
# ---------------------------------------------------------------------------
echo "Syncing .env and restarting containers..."
for i in $(seq 1 10); do
  if scp -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "$SCRIPT_DIR/.env" "root@${RESERVED_IP}:/opt/ibkr-relay/.env" 2>/dev/null; then
    break
  fi
  sleep 5
done

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "root@${RESERVED_IP}" \
  "cd /opt/ibkr-relay && docker compose up -d --force-recreate" 2>&1 | tail -5

# ---------------------------------------------------------------------------
# 5. Delete the snapshot (droplet is running, no longer needed)
# ---------------------------------------------------------------------------
echo "Deleting snapshot $SNAPSHOT_ID..."
curl -s -X DELETE -H "$AUTH" "$API/snapshots/$SNAPSHOT_ID" > /dev/null

# ---------------------------------------------------------------------------
# 6. Clean up pause state
# ---------------------------------------------------------------------------
rm -f "$STATE_FILE"

echo ""
echo "============================================"
echo "  Resumed successfully!"
echo "============================================"
echo ""
echo "  Droplet ID:   $DROPLET_ID"
echo "  Reserved IP:  $RESERVED_IP"
echo "  Snapshot deleted (no longer billed)"
echo ""
echo "  Next steps:"
echo "  1. Open https://${VNC_DOMAIN:-vnc.example.com} to complete 2FA"
echo "  2. The poller will resume automatically"
echo ""
echo "============================================"
