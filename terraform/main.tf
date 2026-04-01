terraform {
  required_version = ">= 1.6.0"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.0"
    }
  }
}

provider "digitalocean" {
  token = var.do_token
}

# ---------------------------------------------------------------------------
# Auto-detect deployer's public IP for firewall rules
# ---------------------------------------------------------------------------
data "http" "deployer_ip" {
  url = "https://api.ipify.org"
}

locals {
  deployer_ip = chomp(data.http.deployer_ip.response_body)
}

# ---------------------------------------------------------------------------
# SSH key — auto-generated, no user setup needed
# ---------------------------------------------------------------------------
resource "tls_private_key" "deploy" {
  algorithm = "ED25519"
}

resource "digitalocean_ssh_key" "deploy" {
  name       = "ibkr-relay-deploy"
  public_key = tls_private_key.deploy.public_key_openssh
}

# ---------------------------------------------------------------------------
# Droplet
# ---------------------------------------------------------------------------
resource "digitalocean_droplet" "relay" {
  image    = "ubuntu-24-04-x64"
  name     = "ibkr-relay"
  region   = var.droplet_region
  size     = "s-1vcpu-2gb"
  ssh_keys = [digitalocean_ssh_key.deploy.fingerprint]

  user_data = file("${path.module}/cloud-init.sh")

  connection {
    type        = "ssh"
    host        = self.ipv4_address
    user        = "root"
    private_key = tls_private_key.deploy.private_key_openssh
  }

  # Wait for cloud-init to finish (Docker install + repo clone)
  provisioner "remote-exec" {
    inline = [
      "cloud-init status --wait",
    ]
  }

  # Transfer .env with secrets (NOT in user_data — metadata API readable)
  provisioner "file" {
    content = templatefile("${path.module}/env.tftpl", {
      tws_userid     = var.tws_userid
      tws_password   = var.tws_password
      trading_mode   = var.trading_mode
      vnc_password   = var.vnc_password
      webhook_url    = var.webhook_url
      webhook_secret = var.webhook_secret
      time_zone      = var.time_zone
    })
    destination = "/opt/ibkr-relay/.env"
  }

  # Start the stack
  provisioner "remote-exec" {
    inline = [
      "cd /opt/ibkr-relay && docker compose up -d",
    ]
  }
}

# ---------------------------------------------------------------------------
# Firewall — restrict SSH + noVNC to deployer IP only
# ---------------------------------------------------------------------------
resource "digitalocean_firewall" "relay" {
  name        = "ibkr-relay-fw"
  droplet_ids = [digitalocean_droplet.relay.id]

  # SSH
  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["${local.deployer_ip}/32"]
  }

  # noVNC (browser-based VNC for 2FA)
  inbound_rule {
    protocol         = "tcp"
    port_range       = "6080"
    source_addresses = ["${local.deployer_ip}/32"]
  }

  # All outbound (DNS, HTTPS for Docker pulls, IBKR API, etc.)
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
