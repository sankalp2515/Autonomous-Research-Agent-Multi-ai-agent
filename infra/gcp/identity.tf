# ── Sign-in: Google Cloud Identity Platform ──────────────────────────────────
#
# Replaces Supabase Auth. Users sign in with email + password (verified email
# required, enforced in the app) or "Continue with Google". The API verifies
# the resulting ID tokens itself (app/api/deps.py) against Google's public keys,
# with this project as audience and issuer, so no service account or secret is
# needed on the request path.
#
# Not in Terraform, on purpose:
#   * the OAuth client for Google sign-in: create it in APIs & Services ->
#     Credentials (type "Web application", redirect URI
#     https://<project>.firebaseapp.com/__/auth/handler) and pass its id/secret
#     as variables; Google does not let Terraform create external OAuth clients;
#   * email templates and the sender name: Identity Platform -> Settings ->
#     Templates;
#   * email enumeration protection: Identity Platform -> Settings -> User
#     actions. Turn it ON (the app already never reveals whether an address
#     has an account; this closes the API path too).
# docs/RUNBOOK.md "Switching sign-in to Identity Platform" walks through them.

resource "google_identity_platform_config" "default" {
  project = var.project_id

  sign_in {
    allow_duplicate_emails = false
    email {
      enabled           = true
      password_required = true
    }
  }

  # Hosts allowed to complete a sign-in redirect. The auth domain itself must be
  # listed or the Google popup's handler is refused.
  authorized_domains = concat(
    [
      "${var.project_id}.firebaseapp.com",
      trimprefix(local.web_url, "https://"),
    ],
    var.extra_authorized_domains,
  )

  depends_on = [google_project_service.apis]
}

resource "google_identity_platform_default_supported_idp_config" "google" {
  count = var.google_oauth_client_id == "" ? 0 : 1

  project       = var.project_id
  idp_id        = "google.com"
  enabled       = true
  client_id     = var.google_oauth_client_id
  client_secret = var.google_oauth_client_secret

  depends_on = [google_identity_platform_config.default]
}

# Public values the web build needs (VITE_IDP_*). The browser API key is a
# client identifier, not a secret: restrict it to the web origin in
# APIs & Services -> Credentials (HTTP referrers + Identity Toolkit and Token
# Service APIs only). Marked sensitive only to keep it out of plan output.
output "identity_platform_api_key" {
  value     = google_identity_platform_config.default.client[0].api_key
  sensitive = true
}

output "identity_platform_auth_domain" {
  value = "${var.project_id}.firebaseapp.com"
}
