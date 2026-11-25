# ── Cloud Run: api, worker, web, and the migrate job ────────────────────────
#
# Terraform owns the SHAPE of each service (env, secrets, scaling, probes,
# network). CI owns the IMAGE: `gcloud run deploy --image ...<sha>` - so image
# is ignored here and Terraform never rolls a deploy back by accident.

locals {
  common_env = {
    APP_ENV             = "prod"
    AUTH_DISABLED       = "false"
    DB_AUTO_CREATE      = "false"
    LOG_FORMAT          = "json"
    SUPABASE_URL        = var.supabase_url
    CORS_ALLOW_ORIGINS  = jsonencode([local.web_url])
    APP_BASE_URL        = local.web_url
    TRUST_FORWARDED_FOR = "true"
    BLOB_BACKEND        = "gcs"
    GCS_BUCKET          = google_storage_bucket.library.name
    VECTOR_BACKEND      = "pgvector"
    VERTEX_PROJECT      = var.project_id
    VERTEX_LOCATION     = "global"
    VERTEX_MODEL        = var.vertex_model
    OTEL_ENABLED        = "false"
    SENTRY_DSN          = var.sentry_dsn
    # Connection budget: db-g1-small allows 100. 5 api + 3 worker instances x
    # (5 + 5 overflow) = 80, leaving room for the migrate job and an operator.
    DB_POOL_SIZE    = "5"
    DB_MAX_OVERFLOW = "5"
  }
  common_secrets = {
    DATABASE_URL  = google_secret_manager_secret.generated["database-url"].secret_id
    REDIS_URL     = google_secret_manager_secret.generated["redis-url"].secret_id
    METRICS_TOKEN = google_secret_manager_secret.generated["metrics-token"].secret_id
  }
}

resource "google_cloud_run_v2_service" "api" {
  name                = "${var.name}-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels
  depends_on          = [google_project_service.apis, google_secret_manager_secret_version.generated]

  template {
    service_account                  = google_service_account.api.email
    timeout                          = "3600s" # SSE run-progress streams
    max_instance_request_concurrency = 40
    scaling {
      min_instance_count = var.api_min_instances
      max_instance_count = var.api_max_instances
    }
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.run.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = local.placeholder
      ports {
        container_port = 8000
      }
      resources {
        limits            = { cpu = "2", memory = "4Gi" } # NLI + embeddings in-process
        cpu_idle          = true
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.common_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/livez"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 24 # model load can take ~60-90s on a cold instance
      }
      liveness_probe {
        http_get {
          path = "/livez"
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

resource "google_cloud_run_v2_service" "worker" {
  name                = "${var.name}-worker"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_INTERNAL_ONLY" # serves only probes and /metrics
  deletion_protection = false
  labels              = local.labels
  depends_on          = [google_project_service.apis, google_secret_manager_secret_version.generated]

  template {
    service_account = google_service_account.worker.email
    scaling {
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }
    vpc_access {
      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.run.id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }
    containers {
      image = local.placeholder
      args  = ["python", "-m", "app.worker"]
      ports {
        container_port = 8080 # the worker's health server listens on $PORT
      }
      resources {
        limits = { cpu = var.worker_cpu, memory = var.worker_memory }
        # Always-allocated CPU: the worker does its work OUTSIDE requests, and a
        # throttled CPU would stall runs between probe hits.
        cpu_idle          = false
        startup_cpu_boost = true
      }
      dynamic "env" {
        for_each = merge(local.common_env, { WORKER_SHUTDOWN_GRACE_SECONDS = "8" })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.common_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
      startup_probe {
        http_get {
          path = "/livez"
        }
        period_seconds    = 5
        failure_threshold = 24
      }
      liveness_probe {
        http_get {
          path = "/readyz" # loop ticked in the last 60s and Redis reachable
        }
        period_seconds    = 30
        failure_threshold = 4
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

resource "google_cloud_run_v2_service" "web" {
  name                = "${var.name}-web"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels
  depends_on          = [google_project_service.apis]

  template {
    service_account = google_service_account.web.email
    timeout         = "3600s" # proxies SSE
    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
    containers {
      image = local.placeholder
      ports {
        container_port = 8080
      }
      resources {
        limits   = { cpu = "1", memory = "256Mi" }
        cpu_idle = true
      }
      env {
        name  = "API_UPSTREAM"
        value = local.api_url
      }
      env {
        name  = "API_HOST"
        value = trimprefix(local.api_url, "https://")
      }
      startup_probe {
        http_get {
          path = "/livez"
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }
}

# Public: the API authenticates every request itself (Supabase JWT); the web
# tier serves a static app.
resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = {
    api = google_cloud_run_v2_service.api.name
    web = google_cloud_run_v2_service.web.name
  }
  name     = each.value
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Runs `alembic upgrade head` once per deploy, BEFORE new revisions take
# traffic. Expand-only migrations (docs/RUNBOOK.md) keep the previous revision
# working against the new schema, so a rollback never needs a downgrade.
resource "google_cloud_run_v2_job" "migrate" {
  name                = "${var.name}-migrate"
  location            = var.region
  deletion_protection = false
  labels              = local.labels
  depends_on          = [google_project_service.apis, google_secret_manager_secret_version.generated]

  template {
    task_count = 1
    template {
      service_account = google_service_account.worker.email
      max_retries     = 0 # a failed migration must stop the deploy, not retry blindly
      timeout         = "900s"
      vpc_access {
        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.run.id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }
      containers {
        image = local.placeholder
        args  = ["alembic", "upgrade", "head"]
        resources {
          limits = { cpu = "1", memory = "1Gi" }
        }
        env {
          name  = "APP_ENV"
          value = "prod"
        }
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = local.common_secrets.DATABASE_URL
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }
}
