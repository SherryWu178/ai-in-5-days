# Copyright 2026 Google LLC

resource "google_service_account" "canteen_sa" {
  account_id   = "canteen-specialist-sa"
  display_name = "Service Account for Singapore Corporate Canteen AI Agent"
}

resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.canteen_sa.email}"
}

resource "google_project_iam_member" "trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.canteen_sa.email}"
}

resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.canteen_sa.email}"
}

resource "google_storage_bucket_iam_member" "menu_bucket_admin" {
  bucket = google_storage_bucket.menu_bucket.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.canteen_sa.email}"
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.canteen_sa.email}"
}
