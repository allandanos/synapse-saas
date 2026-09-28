output "api_url" {
  description = "Public URL of the API service"
  value       = google_cloud_run_v2_service.api.uri
}

output "web_url" {
  description = "Public URL of the console (empty when deploy_web = false)"
  value       = var.deploy_web ? google_cloud_run_v2_service.web[0].uri : ""
}

output "migrate_job_name" {
  description = "Cloud Run job for migrations + seeds — execute once per deploy"
  value       = google_cloud_run_v2_job.migrate.name
}

output "worker_job_name" {
  description = "Cloud Run job that runs one pass of every worker job; Cloud Scheduler triggers it"
  value       = google_cloud_run_v2_job.worker_tick.name
}

output "scheduler_job_name" {
  description = "Cloud Scheduler job driving the worker tick"
  value       = google_cloud_scheduler_job.worker_tick.name
}

output "service_account_email" {
  description = "Run services' identity — grant extra roles (e.g. GCS/S3 access) here"
  value       = google_service_account.synapse.email
}
