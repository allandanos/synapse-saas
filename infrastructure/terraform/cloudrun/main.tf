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
  description = "Image ref for the console"
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
  type    = string
  default = ""
  description = "Console origin for CORS, e.g. https://console.example.com"
}

variable "billing_provider" {
  type    = string
  default = "manual"
}

variable "min_api_instances" {
  type    = number
  default = 1
  description = "Keep ≥1 warm to avoid cold-start latency on the auth path"
}

variable "max_api_instances" {
  type    = number
  default = 10
}

variable "worker_instances" {
  type    = number
  default = 1
  description = "Outbox dispatch is SKIP LOCKED-safe; scale freely"
}

locals {
  labels = {
    app     = "synapse-saas"
    service = "framework"
  }
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
        secret_manager = {
          secret = google_secret_manager_secret.database_url.secret_id
          version = "latest"
        }
      }
    },
    {
      name = "SYNAPSE_SECRET_KEY"
      value_source = {
        secret_manager = {
          secret = google_secret_manager_secret.secret_key.secret_id
          version = "latest"
        }
      }
    },
  ]
  redis_env = var.redis_url != "" ? [
    {
      name = "SYNAPSE_REDIS_URL"
      value_source = {
        secret_manager = {
          secret = google_secret_manager_secret.redis_url[0].secret_id
          version = "latest"
        }
      }
    },
  ] : []
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
        for_each = concat(local.common_env, local.secret_env, local.redis_env)
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
          path = "/healthz"
          port = 8000
        }
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
      }

    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "api_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Worker ────────────────────────────────────────────────────────────────────

resource "google_cloud_run_v2_job" "worker_tick" {
  project  = var.project_id
  name     = "synapse-worker-tick"
  location = var.region
  labels   = local.labels

  template {
    template {
      service_account = google_service_account.synapse.email
      containers {
        image = var.api_image
        command = [
          "/bin/sh", "-c",
          # One full pass of every cron job; Cloud Scheduler triggers it
          "synapse-cli migrate && synapse-cli seed"
        ]
        dynamic "env" {
        for_each = concat(local.common_env, local.secret_env, local.redis_env)
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
    }
  }
}
