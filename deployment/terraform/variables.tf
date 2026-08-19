# Copyright 2026 Google LLC

variable "project_id" {
  type        = string
  description = "Google Cloud Project ID where the Singapore Corporate Canteen AI will be deployed."
}

variable "region" {
  type        = string
  default     = "asia-southeast1" # Singapore region for lowest latency to MBC2 corporate canteens
  description = "Google Cloud region for Cloud Run, Vertex AI, and Cloud Storage."
}

variable "service_name" {
  type        = string
  default     = "singapore-canteen-specialist-ai"
  description = "Cloud Run service name for the ADK 2.0 Web Portal & Admin API."
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Deployment environment (production / staging)."
}

variable "container_image" {
  type        = string
  default     = "asia-southeast1-docker.pkg.dev/my-project/canteen-repo/agent:latest"
  description = "Docker container image URI in Artifact Registry."
}
