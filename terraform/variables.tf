variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "tws_userid" {
  description = "IBKR account username"
  type        = string
  sensitive   = true
}

variable "tws_password" {
  description = "IBKR account password"
  type        = string
  sensitive   = true
}

variable "trading_mode" {
  description = "IBKR trading mode: paper or live"
  type        = string
  default     = "paper"

  validation {
    condition     = contains(["paper", "live"], var.trading_mode)
    error_message = "trading_mode must be 'paper' or 'live'."
  }
}

variable "vnc_password" {
  description = "Password for noVNC browser access (used for 2FA)"
  type        = string
  sensitive   = true
}

variable "webhook_url" {
  description = "Target URL for order fill webhook notifications"
  type        = string
  sensitive   = true
}

variable "webhook_secret" {
  description = "HMAC-SHA256 secret for signing webhook payloads"
  type        = string
  sensitive   = true
}

variable "flex_token" {
  description = "IBKR Flex Web Service token"
  type        = string
  sensitive   = true
}

variable "flex_query_id" {
  description = "IBKR Trade Confirmation Flex Query ID"
  type        = string
}

variable "poll_interval" {
  description = "Flex poll interval in seconds"
  type        = string
  default     = "600"
}

variable "time_zone" {
  description = "Timezone in tz database format"
  type        = string
  default     = "America/New_York"
}

variable "droplet_region" {
  description = "DigitalOcean region for the droplet"
  type        = string
  default     = "nyc3"
}

variable "vnc_domain" {
  description = "Domain for HTTPS VNC access (must have DNS A record pointing to droplet)"
  type        = string
}

variable "trade_domain" {
  description = "Domain for HTTPS trade API (must have DNS A record pointing to droplet)"
  type        = string
}

variable "api_token" {
  description = "Bearer token for securing the /ibkr/* API endpoints"
  type        = string
  sensitive   = true
}
