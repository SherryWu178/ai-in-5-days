# Copyright 2026 Google LLC

# Cloud Storage Bucket for live today_menu.json ingestion and admin uploads
resource "google_storage_bucket" "menu_bucket" {
  name                        = "${var.project_id}-singapore-canteen-menus"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  cors {
    origin          = ["*"]
    method          = ["GET", "POST", "PUT"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}
