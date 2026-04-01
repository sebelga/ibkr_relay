output "droplet_ip" {
  description = "Public IPv4 address of the droplet"
  value       = digitalocean_droplet.relay.ipv4_address
}

output "vnc_url" {
  description = "noVNC URL for browser-based 2FA access"
  value       = "http://${digitalocean_droplet.relay.ipv4_address}:6080"
}

output "ssh_private_key" {
  description = "SSH private key for accessing the droplet (save to ~/.ssh/ibkr-relay)"
  value       = tls_private_key.deploy.private_key_openssh
  sensitive   = true
}
