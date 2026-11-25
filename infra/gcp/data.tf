# ── Network: a private VPC; nothing stateful gets a public IP ───────────────
resource "google_compute_network" "vpc" {
  name                    = "${var.name}-vpc"
  auto_create_subnetworks = false
  depends_on              = [google_project_service.apis]
}

# Cloud Run Direct VPC egress takes instance IPs from this subnet.
resource "google_compute_subnetwork" "run" {
  name                     = "${var.name}-run"
  network                  = google_compute_network.vpc.id
  region                   = var.region
  ip_cidr_range            = "10.10.0.0/24"
  private_ip_google_access = true
}

# Private Service Access: Cloud SQL and Memorystore live in Google's producer
# network, peered into ours.
resource "google_compute_global_address" "psa" {
  name          = "${var.name}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa.name]
}

# ── Cloud SQL: Postgres 16 with pgvector ────────────────────────────────────
resource "google_sql_database_instance" "db" {
  name                = "${var.name}-db"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = true
  depends_on          = [google_service_networking_connection.psa]

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = var.db_high_availability ? "REGIONAL" : "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true
    user_labels       = local.labels

    ip_configuration {
      ipv4_enabled                                  = false # private IP only
      private_network                               = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "20:30" # 02:00 IST
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
      }
    }

    maintenance_window {
      day          = 7  # Sunday
      hour         = 21 # 02:30 IST
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      record_application_tags = true
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "1000" # log statements slower than 1s
    }
    database_flags {
      name  = "max_connections"
      value = "100"
    }
  }
}

resource "google_sql_database" "app" {
  name     = var.name
  instance = google_sql_database_instance.db.name
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_user" "app" {
  name     = var.name
  instance = google_sql_database_instance.db.name
  password = random_password.db.result
}

# ── Memorystore Redis: queue, cache, locks, progress pub/sub ────────────────
resource "google_redis_instance" "cache" {
  name               = "${var.name}-redis"
  tier               = "BASIC" # disposable by design: everything in Redis is rebuildable from Postgres
  memory_size_gb     = var.redis_memory_gb
  region             = var.region
  redis_version      = "REDIS_7_2"
  authorized_network = google_compute_network.vpc.id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"
  auth_enabled       = true
  labels             = local.labels
  redis_configs = {
    # Queue and lock keys must never be evicted to make room for cache entries.
    "maxmemory-policy" = "volatile-lru"
  }
  depends_on = [google_service_networking_connection.psa]
}

# ── Paper library ───────────────────────────────────────────────────────────
resource "google_storage_bucket" "library" {
  name                        = "${var.project_id}-library"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
  labels                      = local.labels
  soft_delete_policy {
    retention_duration_seconds = 604800 # 7 days to undo an accidental delete
  }
}

# ── Images ──────────────────────────────────────────────────────────────────
resource "google_artifact_registry_repository" "images" {
  repository_id = var.name
  location      = var.region
  format        = "DOCKER"
  labels        = local.labels
  depends_on    = [google_project_service.apis]

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20 # enough to roll back weeks, not enough to cost money
    }
  }
  cleanup_policies {
    id     = "delete-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days
    }
  }
}
