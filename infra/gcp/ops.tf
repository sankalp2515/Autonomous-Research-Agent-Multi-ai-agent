# ── Alerting: someone is told before a user has to tell them ────────────────
resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  display_name = "Veriscope on-call"
  type         = "email"
  labels       = { email_address = var.alert_email }
}

locals {
  channels = google_monitoring_notification_channel.email[*].id
}

resource "google_monitoring_uptime_check_config" "web" {
  display_name = "veriscope web /livez"
  timeout      = "10s"
  period       = "300s"
  http_check {
    path         = "/livez"
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(local.web_url, "https://")
    }
  }
}

resource "google_monitoring_uptime_check_config" "api" {
  display_name = "veriscope api /readyz (database, redis, vectors, storage)"
  timeout      = "10s"
  period       = "300s"
  http_check {
    path         = "/readyz"
    use_ssl      = true
    validate_ssl = true
  }
  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = trimprefix(local.api_url, "https://")
    }
  }
}

resource "google_monitoring_alert_policy" "uptime" {
  display_name          = "Veriscope is down"
  combiner              = "OR"
  notification_channels = local.channels
  conditions {
    display_name = "uptime check failing"
    condition_threshold {
      filter          = "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\" AND resource.type=\"uptime_url\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "300s"
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.host"]
      }
    }
  }
}

resource "google_monitoring_alert_policy" "api_5xx" {
  display_name          = "Veriscope API 5xx rate"
  combiner              = "OR"
  notification_channels = local.channels
  conditions {
    display_name = "more than 5 server errors per minute for 5 minutes"
    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.label.service_name=\"${google_cloud_run_v2_service.api.name}\" AND metric.label.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "300s"
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }
}

resource "google_monitoring_alert_policy" "sql_disk" {
  display_name          = "Cloud SQL disk above 80%"
  combiner              = "OR"
  notification_channels = local.channels
  conditions {
    display_name = "disk utilization"
    condition_threshold {
      filter          = "metric.type=\"cloudsql.googleapis.com/database/disk/utilization\" AND resource.type=\"cloudsql_database\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0.8
      duration        = "600s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MEAN"
      }
    }
  }
}

# ── Budget: the "use it wisely" guard ───────────────────────────────────────
resource "google_billing_budget" "monthly" {
  count           = var.billing_account == "" ? 0 : 1
  billing_account = var.billing_account
  display_name    = "Veriscope monthly"
  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }
  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_usd)
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
  dynamic "all_updates_rule" {
    for_each = var.alert_email == "" ? [] : [1]
    content {
      monitoring_notification_channels = local.channels
      disable_default_iam_recipients   = false
    }
  }
}

output "web_url" {
  value = local.web_url
}

output "api_url" {
  value = local.api_url
}

output "image_prefix" {
  value = local.image_prefix
}

output "workload_identity_provider" {
  description = "Set as the GCP_WORKLOAD_IDENTITY_PROVIDER repository variable."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Set as the GCP_DEPLOYER_SA repository variable."
  value       = google_service_account.deployer.email
}
