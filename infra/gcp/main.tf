# Veriscope on Google Cloud - the whole production footprint.
#
#   web (Cloud Run)  ->  api (Cloud Run)  ->  Cloud SQL Postgres 16 + pgvector
#                                         ->  Memorystore Redis (queue, cache)
#   worker (Cloud Run, always-on)         ->  same, + GCS paper library
#   migrate (Cloud Run Job)               ->  alembic upgrade head, before deploys
#   Vertex AI (Gemini) via the runtime service account - no API keys.
#
# Private by default: Cloud SQL and Redis have NO public address; Cloud Run
# reaches them through Direct VPC egress. Secrets live in Secret Manager and are
# mounted as env vars; no credential is ever in an image, a repo, or CI.
#
# See infra/gcp/README.md for bootstrap order, cost, and what is deliberately
# NOT here yet (custom domain + Cloud Armor).

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # State holds generated secrets (DB password). Keep it in a PRIVATE,
  # versioned bucket - create it once by hand, then uncomment:
  # backend "gcs" {
  #   bucket = "veriscope-515119-tfstate"
  #   prefix = "prod"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  # Cloud Run's deterministic URL: https://<service>-<project number>.<region>.run.app
  # Known before the service exists, which breaks the web<->api dependency cycle.
  run_suffix   = "${data.google_project.this.number}.${var.region}.run.app"
  web_url      = var.public_base_url != "" ? var.public_base_url : "https://${var.name}-web-${local.run_suffix}"
  api_url      = "https://${var.name}-api-${local.run_suffix}"
  image_prefix = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
  placeholder  = "us-docker.pkg.dev/cloudrun/container/hello"
  labels       = { app = var.name, env = "prod", managed-by = "terraform" }
}

# ── APIs ─────────────────────────────────────────────────────────────────────
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "redis.googleapis.com",
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "billingbudgets.googleapis.com",
    "identitytoolkit.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}
