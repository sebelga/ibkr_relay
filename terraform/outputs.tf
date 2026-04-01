output "droplet_ip" {
  description = "Reserved (static) public IP of the droplet"
  value       = digitalocean_reserved_ip.relay.ip_address
}

output "vnc_url" {
  description = "noVNC URL for browser-based 2FA access"
  value       = "https://${var.vnc_domain}"
}

output "trade_url" {
  description = "Trade API base URL"
  value       = "https://${var.trade_domain}"
}

output "ssh_private_key" {
  description = "SSH private key for accessing the droplet (save to ~/.ssh/ibkr-relay)"
  value       = tls_private_key.deploy.private_key_openssh
  sensitive   = true
}
