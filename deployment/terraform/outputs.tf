# Copyright 2026 Google LLC

output "cloud_run_service_url" {
  description = "Public URL of the deployed Singapore Corporate Canteen AI Agent."
  value       = google_cloud_run_v2_service.canteen_agent_service.uri
}

output "menu_storage_bucket" {
  description = "GCS bucket storing today_menu.json live daily corporate canteen menus."
  value       = google_storage_bucket.menu_bucket.name
}

output "service_account_email" {
  description = "Service Account identity running the Cloud Run service."
  value       = google_service_account.canteen_sa.email
}
