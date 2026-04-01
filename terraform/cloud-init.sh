#!/bin/bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Cloud-init script: Install Docker and clone the project repo.
# This runs as root on first boot. NO SECRETS here — they are transferred
# separately via Terraform file provisioner over SSH.
# ---------------------------------------------------------------------------

# Install Docker via official convenience script
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Clone the project repo
git clone https://github.com/OWNER/ibkr_relay.git /opt/ibkr-relay

# Directory is ready — Terraform provisioners will:
# 1. Transfer .env with secrets
# 2. Run docker compose up -d
