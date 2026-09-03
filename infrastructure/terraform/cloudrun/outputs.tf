output "api_url" {
  description = "Public URL of the API service"
  value       = google_cloud_run_v2_service.api.uri
}

output "worker_job_name" {
  description = "Cloud Run job for migrations/seeds — trigger on deploy"
  value       = google_cloud_run_v2_job.worker_tick.name
}

output "service_account_email" {
  description = "Run services' identity — grant extra roles (e.g. S3/GCS access) here"
  value       = google_service_account.synapse.email
}
