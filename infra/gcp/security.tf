# ── Identities: one per workload, least privilege ───────────────────────────
resource "google_service_account" "api" {
  account_id   = "${var.name}-api"
  display_name = "Veriscope API (Cloud Run)"
}

resource "google_service_account" "worker" {
  account_id   = "${var.name}-worker"
  display_name = "Veriscope worker + migrations (Cloud Run)"
}

resource "google_service_account" "web" {
  account_id   = "${var.name}-web"
  display_name = "Veriscope web tier (Cloud Run) - no data access"
}

resource "google_service_account" "deployer" {
  account_id   = "${var.name}-deployer"
  display_name = "GitHub Actions deployer (Workload Identity Federation)"
}

locals {
  runtime_sas = {
    api    = google_service_account.api.email
    worker = google_service_account.worker.email
  }
}

resource "google_project_iam_member" "runtime" {
  for_each = {
    for pair in setproduct(keys(local.runtime_sas), [
      "roles/aiplatform.user", # Vertex Gemini
      "roles/logging.logWriter",
      "roles/monitoring.metricWriter",
      "roles/cloudtrace.agent",
      "roles/cloudsql.client",
    ]) : "${pair[0]}-${pair[1]}" => { sa = local.runtime_sas[pair[0]], role = pair[1] }
  }
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${each.value.sa}"
}

resource "google_storage_bucket_iam_member" "library" {
  for_each = local.runtime_sas
  bucket   = google_storage_bucket.library.name
  role     = "roles/storage.objectUser"
  member   = "serviceAccount:${each.value}"
}

# ── Secrets ─────────────────────────────────────────────────────────────────
# Generated here: database-url, redis-url, metrics-token.
# Set out-of-band (never in Terraform, never in git):
#   gcloud secrets versions add veriscope-smtp-password --data-file=-
resource "random_password" "metrics" {
  length  = 40
  special = false
}

locals {
  generated_secrets = {
    "database-url"  = "postgresql+asyncpg://${google_sql_user.app.name}:${random_password.db.result}@${google_sql_database_instance.db.private_ip_address}:5432/${google_sql_database.app.name}?ssl=require"
    "redis-url"     = "redis://:${google_redis_instance.cache.auth_string}@${google_redis_instance.cache.host}:${google_redis_instance.cache.port}/0"
    "metrics-token" = random_password.metrics.result
  }
  external_secrets = ["smtp-password", "semantic-scholar-api-key"]
}

resource "google_secret_manager_secret" "generated" {
  for_each  = local.generated_secrets
  secret_id = "${var.name}-${each.key}"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "generated" {
  for_each    = local.generated_secrets
  secret      = google_secret_manager_secret.generated[each.key].id
  secret_data = each.value
}

resource "google_secret_manager_secret" "external" {
  for_each  = toset(local.external_secrets)
  secret_id = "${var.name}-${each.value}"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_iam_member" "runtime_generated" {
  for_each = {
    for pair in setproduct(keys(local.runtime_sas), keys(local.generated_secrets)) :
    "${pair[0]}-${pair[1]}" => { sa = local.runtime_sas[pair[0]], secret = pair[1] }
  }
  secret_id = google_secret_manager_secret.generated[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa}"
}

resource "google_secret_manager_secret_iam_member" "runtime_external" {
  for_each = {
    for pair in setproduct(keys(local.runtime_sas), local.external_secrets) :
    "${pair[0]}-${pair[1]}" => { sa = local.runtime_sas[pair[0]], secret = pair[1] }
  }
  secret_id = google_secret_manager_secret.external[each.value.secret].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa}"
}

# ── GitHub Actions -> GCP without a key file (Workload Identity Federation) ──
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only this repository's main branch and version tags may deploy.
  attribute_condition = "assertion.repository == '${var.github_repository}' && (assertion.ref == 'refs/heads/main' || assertion.ref.startsWith('refs/tags/v'))"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_project_iam_member" "deployer" {
  for_each = toset([
    "roles/run.developer",           # deploy new revisions, execute the migrate job
    "roles/artifactregistry.writer", # push images
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

# The deployer may deploy revisions that RUN AS the runtime identities, and
# nothing else.
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = {
    api    = google_service_account.api.name
    worker = google_service_account.worker.name
    web    = google_service_account.web.name
  }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
