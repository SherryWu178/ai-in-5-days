# Copyright 2026 Google LLC

resource "google_cloud_run_v2_service" "canteen_agent_service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.canteen_sa.email

    scaling {
      min_instance_count = 1
      max_instance_count = 10
    }

    containers {
      image = var.container_image

      resources {
        limits = {
          cpu    = "2"
          memory = "1024Mi"
        }
      }

      ports {
        container_port = 8000
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "1"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "MENU_GCS_BUCKET"
        value = google_storage_bucket.menu_bucket.name
      }

      env {
        name  = "FAST_MODEL"
        value = "gemini-3.7-flash"
      }

      env {
        name  = "REASONING_PRO_MODEL"
        value = "gemini-3.1-pro"
      }

      env {
        name  = "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"
        value = "true"
      }

      env {
        name  = "ENABLE_MODEL_ARMOR_SAFETY"
        value = "true"
      }

      liveness_probe {
        http_get {
          path = "/api/health"
        }
        initial_delay_seconds = 15
        period_seconds        = 10
      }
    }
  }

  depends_on = [
    google_project_service.apis
  ]
}

# Allow public access to the interactive portal (or configure IAP for Googlers only)
resource "google_cloud_run_service_iam_member" "public_access" {
  location = google_cloud_run_v2_service.canteen_agent_service.location
  service  = google_cloud_run_v2_service.canteen_agent_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
