# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Cloud SQL PostgreSQL Instance for persistent multi-tenant User Profile Memory & pgvector
resource "google_sql_database_instance" "canteen_db_instance" {
  name             = "${var.service_name}-db"
  database_version = "POSTGRES_15"
  region           = var.region

  settings {
    tier              = "db-f1-micro"
    availability_type = "ZONAL"
    disk_size         = 10
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "canteen_db" {
  name     = "canteen_agent_db"
  instance = google_sql_database_instance.canteen_db_instance.name
}

resource "google_sql_user" "canteen_db_user" {
  name     = "canteen_app_user"
  instance = google_sql_database_instance.canteen_db_instance.name
  password = "canteen_secure_password_replace_with_secret"
}
