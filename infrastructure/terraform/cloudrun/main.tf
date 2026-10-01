# Synapse SaaS on Cloud Run — API + Worker, secrets from Secret Manager.
#
# Postgres/Redis are intentionally NOT created here: pair with Cloud SQL +
# Memorystore (or any reachable instances) and pass their URLs as variables.
# See README.md in this directory.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

variable "project_id" {
  type        = string
  description = "GCP project id"
}

variable "region" {
  type    = string
  default = "asia-southeast1"
}

variable "api_image" {
  type        = string
  description = "Image ref for api + worker (same image, different entrypoint)"
  default     = "gcr.io/PROJECT/synapse-api:latest"
}

variable "web_image" {
  type        = string
  description = "Image ref for the console (deployed as the synapse-web service when deploy_web = true)"
  default     = "gcr.io/PROJECT/synapse-web:latest"
}

variable "database_url" {
  type        = string
  sensitive   = true
  description = "postgresql+asyncpg://… (Cloud SQL or any reachable Postgres)"
}

variable "redis_url" {
  type        = string
  sensitive   = true
  default     = ""
  description = "redis://… (Memorystore). Empty ⇒ in-process fallback caches."
}

variable "secret_key" {
  type        = string
  sensitive   = true
  description = "SYNAPSE_SECRET_KEY — JWT signing + Fernet webhook secrets"
}

variable "web_origin" {
  type        = string
  default     = ""
  description = "Console origin for CORS, e.g. https://console.example.com"
}

variable "billing_provider" {
  type    = string
  default = "manual"
}

variable "min_api_instances" {
  type        = number
  default     = 1
  description = "Keep ≥1 warm to avoid cold-start latency on the auth path"
}

variable "max_api_instances" {
  type    = number
  default = 10
}

variable "manual_webhook_token" {
  type        = string
  sensitive   = true
  default     = ""
  description = "SYNAPSE_MANUAL_WEBHOOK_TOKEN — required when billing_provider = manual with a public invoker"
}

variable "vpc_connector" {
  type        = string
  default     = ""
  description = "Serverless VPC Access connector id (projects/…/locations/…/connectors/…) for private Cloud SQL / Memorystore"
}

variable "worker_schedule" {
  type        = string
  default     = "*/5 * * * *"
  description = "Cloud Scheduler cron for the worker tick (one pass of every job)"
}

variable "deploy_web" {
  type        = bool
  default     = true
  description = "Also deploy the console (web_image) as a Cloud Run service"
}

locals {
  labels = {
    app     = "synapse-saas"
    service = "framework"
  }
}

# ── APIs ──────────────────────────────────────────────────────────────────────

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "iam.googleapis.com",
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ── Secrets ───────────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = "synapse-database-url"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "database_url" {
  secret      = google_secret_manager_secret.database_url.id
  secret_data = var.database_url
}

resource "google_secret_manager_secret" "redis_url" {
  count = var.redis_url != "" ? 1 : 0

  project   = var.project_id
  secret_id = "synapse-redis-url"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "redis_url" {
  count = var.redis_url != "" ? 1 : 0

  secret      = google_secret_manager_secret.redis_url[0].id
  secret_data = var.redis_url
}

resource "google_secret_manager_secret" "secret_key" {
  project   = var.project_id
  secret_id = "synapse-secret-key"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "secret_key" {
  secret      = google_secret_manager_secret.secret_key.id
  secret_data = var.secret_key
}

resource "google_secret_manager_secret" "manual_webhook_token" {
  count = var.manual_webhook_token != "" ? 1 : 0

  project   = var.project_id
  secret_id = "synapse-manual-webhook-token"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "manual_webhook_token" {
  count = var.manual_webhook_token != "" ? 1 : 0

  secret      = google_secret_manager_secret.manual_webhook_token[0].id
  secret_data = var.manual_webhook_token
}

# One Cloud Run service account with least-privilege secret access
resource "google_service_account" "synapse" {
  project      = var.project_id
  account_id   = "synapse-run"
  display_name = "Synapse SaaS Cloud Run services"
}

resource "google_secret_manager_secret_iam_member" "database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse.email}"
}

resource "google_secret_manager_secret_iam_member" "redis_url" {
  count = var.redis_url != "" ? 1 : 0

  secret_id = google_secret_manager_secret.redis_url[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse.email}"
}

resource "google_secret_manager_secret_iam_member" "secret_key" {
  secret_id = google_secret_manager_secret.secret_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse.email}"
}

resource "google_secret_manager_secret_iam_member" "manual_webhook_token" {
  count = var.manual_webhook_token != "" ? 1 : 0

  secret_id = google_secret_manager_secret.manual_webhook_token[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse.email}"
}

# ── Shared env ────────────────────────────────────────────────────────────────

locals {
  common_env = [
    { name = "SYNAPSE_ENV", value = "production" },
    { name = "SYNAPSE_WEB_ORIGIN", value = var.web_origin },
    { name = "SYNAPSE_BILLING_PROVIDER", value = var.billing_provider },
    { name = "SYNAPSE_METRICS_ENABLED", value = "true" },
    { name = "SYNAPSE_AUTO_SYNC_PLANS", value = "true" },
  ]
  secret_env = [
    {
      name = "SYNAPSE_DATABASE_URL"
      value_source = {
        secret_key_ref = {
          secret  = google_secret_manager_secret.database_url.secret_id
          version = "latest"
        }
      }
    },
    {
      name = "SYNAPSE_SECRET_KEY"
      value_source = {
        secret_key_ref = {
          secret  = google_secret_manager_secret.secret_key.secret_id
          version = "latest"
        }
      }
    },
  ]
  manual_token_env = var.manual_webhook_token != "" ? [
    {
      name = "SYNAPSE_MANUAL_WEBHOOK_TOKEN"
      value_source = {
        secret_key_ref = {
          secret  = google_secret_manager_secret.manual_webhook_token[0].secret_id
          version = "latest"
        }
      }
    },
  ] : []
  redis_env = var.redis_url != "" ? [
    {
      name = "SYNAPSE_REDIS_URL"
      value_source = {
        secret_key_ref = {
          secret  = google_secret_manager_secret.redis_url[0].secret_id
          version = "latest"
        }
      }
    },
  ] : []
  all_env = concat(local.common_env, local.secret_env, local.redis_env, local.manual_token_env)
}

# ── API ───────────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "api" {
  project  = var.project_id
  name     = "synapse-api"
  location = var.region
  labels   = local.labels

  template {
    service_account = google_service_account.synapse.email

    annotations = {
      "autoscaling.knative.dev/minScale" = tostring(var.min_api_instances)
      "autoscaling.knative.dev/maxScale" = tostring(var.max_api_instances)
    }

    containers {
      image = var.api_image
      ports {
        container_port = 8000
      }
      dynamic "env" {
        for_each = local.all_env
        content {
          name  = env.value.name
          value = try(env.value.value, null)

          dynamic "value_source" {
            for_each = try(env.value.value_source, null) != null ? [env.value.value_source] : []
            content {
              secret_key_ref {
                secret  = env.value.value_source.secret_key_ref.secret
                version = try(env.value.value_source.secret_key_ref.version, "latest")
              }
            }
          }
        }
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        startup_cpu_boost = true
      }

      startup_probe {
        http_get {
          path = "/readyz" # 503 until the database answers — traffic waits for a ready revision
          port = 8000
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
      }

      liveness_probe {
        http_get {
          path = "/healthz"
          port = 8000
        }
        period_seconds    = 30
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }

    dynamic "vpc_access" {
      for_each = var.vpc_connector != "" ? [var.vpc_connector] : []
      content {
        connector = vpc_access.value
        egress    = "PRIVATE_RANGES_ONLY"
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Jobs ──────────────────────────────────────────────────────────────────────
# Two Cloud Run jobs sharing the API image:
#   synapse-migrate      — schema + seeds; executed once per deploy
#   synapse-worker-tick  — one pass of every worker job (outbox, deliveries,
#                          renewals, partitions, retention); Cloud Scheduler
#                          runs it every `worker_schedule`. No always-on
#                          process is needed on Cloud Run.

locals {
  job_env = local.all_env
}

resource "google_cloud_run_v2_job" "migrate" {
  project  = var.project_id
  name     = "synapse-migrate"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.synapse.email
      containers {
        image   = var.api_image
        command = ["/bin/sh", "-c", "synapse-cli migrate && synapse-cli seed"]
        dynamic "env" {
          for_each = local.job_env
          content {
            name  = env.value.name
            value = try(env.value.value, null)

            dynamic "value_source" {
              for_each = try(env.value.value_source, null) != null ? [env.value.value_source] : []
              content {
                secret_key_ref {
                  secret  = env.value.value_source.secret_key_ref.secret
                  version = try(env.value.value_source.secret_key_ref.version, "latest")
                }
              }
            }
          }
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
      dynamic "vpc_access" {
        for_each = var.vpc_connector != "" ? [var.vpc_connector] : []
        content {
          connector = vpc_access.value
          egress    = "PRIVATE_RANGES_ONLY"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_job" "worker_tick" {
  project  = var.project_id
  name     = "synapse-worker-tick"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.synapse.email
      timeout         = "600s"
      containers {
        image   = var.api_image
        command = ["synapse-cli", "jobs", "run-once", "--all"]
        dynamic "env" {
          for_each = local.job_env
          content {
            name  = env.value.name
            value = try(env.value.value, null)

            dynamic "value_source" {
              for_each = try(env.value.value_source, null) != null ? [env.value.value_source] : []
              content {
                secret_key_ref {
                  secret  = env.value.value_source.secret_key_ref.secret
                  version = try(env.value.value_source.secret_key_ref.version, "latest")
                }
              }
            }
          }
        }
        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }
      }
      dynamic "vpc_access" {
        for_each = var.vpc_connector != "" ? [var.vpc_connector] : []
        content {
          connector = vpc_access.value
          egress    = "PRIVATE_RANGES_ONLY"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# The scheduler runs the worker job as the same service account
resource "google_cloud_run_v2_job_iam_member" "worker_tick_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.worker_tick.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.synapse.email}"
}

resource "google_cloud_scheduler_job" "worker_tick" {
  project     = var.project_id
  region      = var.region
  name        = "synapse-worker-tick"
  description = "One pass of every Synapse worker job"
  schedule    = var.worker_schedule
  time_zone   = "Etc/UTC"

  attempt_deadline = "620s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.worker_tick.name}:run"
    oauth_token {
      service_account_email = google_service_account.synapse.email
    }
  }

  depends_on = [google_project_service.apis, google_cloud_run_v2_job_iam_member.worker_tick_invoker]
}

# ── Console ───────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "web" {
  count = var.deploy_web ? 1 : 0

  project  = var.project_id
  name     = "synapse-web"
  location = var.region
  labels   = local.labels

  template {
    service_account = google_service_account.synapse.email
    containers {
      image = var.web_image
      ports {
        container_port = 3000
      }
      # Runtime config (nothing is baked into the image): the API as browsers
      # reach it. The console's server fetches GET /v1/branding from the same
      # URL (SYNAPSE_API_INTERNAL_URL defaults to it).
      env {
        name  = "SYNAPSE_API_URL"
        value = google_cloud_run_v2_service.api.uri
      }
      env {
        name  = "NODE_ENV"
        value = "production"
      }
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
      startup_probe {
        http_get {
          path = "/healthz"
          port = 3000
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  count = var.deploy_web ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
