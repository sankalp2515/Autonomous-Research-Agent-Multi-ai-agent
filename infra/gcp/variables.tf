variable "project_id" {
  type    = string
  default = "veriscope-515119"
}

variable "region" {
  description = "Mumbai: closest to the team; every service used here is available in it."
  type        = string
  default     = "asia-south1"
}

variable "name" {
  type    = string
  default = "veriscope"
}

variable "github_repository" {
  description = "owner/repo allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "sankalp2515/Autonomous-Research-Agent-Multi-ai-agent"
}

variable "public_base_url" {
  description = "Public https origin users open (custom domain). Empty = the web service's run.app URL."
  type        = string
  default     = ""
}

# ── sign-in ───────────────────────────────────────────────────────────────
variable "auth_provider" {
  description = "Token issuer the API trusts: identity_platform, or supabase to roll back during the cut-over."
  type        = string
  default     = "identity_platform"
  validation {
    condition     = contains(["identity_platform", "supabase"], var.auth_provider)
    error_message = "auth_provider must be identity_platform or supabase."
  }
}

variable "google_oauth_client_id" {
  description = "OAuth 2.0 web client id for 'Continue with Google' (APIs & Services -> Credentials). Empty = Google sign-in not configured."
  type        = string
  default     = ""
}

variable "google_oauth_client_secret" {
  description = "Secret of the OAuth client above. Pass via TF_VAR_google_oauth_client_secret, never a committed tfvars."
  type        = string
  default     = ""
  sensitive   = true
}

variable "extra_authorized_domains" {
  description = "More hosts allowed to complete sign-in redirects (custom domain, staging)."
  type        = list(string)
  default     = []
}

variable "supabase_url" {
  description = "https://<ref>.supabase.co - only used when auth_provider = supabase (cut-over / rollback)."
  type        = string
  default     = ""
}

# ── sizing: defaults are the cheapest configuration that runs the product ──
variable "db_tier" {
  description = "db-g1-small is shared-core (no SLA). Move to db-custom-2-7680 for real traffic."
  type        = string
  default     = "db-g1-small"
}

variable "db_high_availability" {
  description = "REGIONAL doubles the Cloud SQL bill; turn on once there are paying users."
  type        = bool
  default     = false
}

variable "redis_memory_gb" {
  type    = number
  default = 1
}

variable "api_min_instances" {
  description = "0 = scale to zero (cheapest; first request pays a model-loading cold start). 1 for real users."
  type        = number
  default     = 0
}

variable "api_max_instances" {
  type    = number
  default = 5
}

variable "worker_min_instances" {
  description = "The worker pulls from Redis, so at least one must be running for runs to progress."
  type        = number
  default     = 1
}

variable "worker_max_instances" {
  type    = number
  default = 3
}

variable "worker_cpu" {
  type    = string
  default = "2"
}

variable "worker_memory" {
  type    = string
  default = "4Gi"
}

variable "vertex_model" {
  description = "Confirm the exact id in Vertex AI Model Garden for the chosen region before applying."
  type        = string
  default     = "gemini-3.5-flash"
}

variable "alert_email" {
  description = "Receives uptime, error-rate and budget alerts. Empty = no notification channel."
  type        = string
  default     = ""
}

variable "billing_account" {
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX) for the budget alert. Empty = no budget."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  type    = number
  default = 300
}

variable "sentry_dsn" {
  type      = string
  default   = ""
  sensitive = true
}
