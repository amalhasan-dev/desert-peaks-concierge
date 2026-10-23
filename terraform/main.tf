# Infrastructure as Code for the Desert Peaks Park concierge (rubric 5.2).
#
# Provisions everything the agent needs EXCEPT the container image itself,
# which `adk deploy cloud_run` (or Cloud Build) builds and deploys:
#   * required Google Cloud APIs
#   * a least-privilege runtime service account for Cloud Run
#   * Secret Manager secret for an optional Gemini API key (rubric 5.3)
#   * permissions for Cloud Build to test + deploy (CI/CD)
#
# Usage (Cloud Shell):
#   cd terraform
#   terraform init
#   terraform apply -var="project_id=YOUR_PROJECT_ID"

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}

# ---------- APIs ----------
locals {
  services = [
    "aiplatform.googleapis.com",       # Gemini on Vertex AI, Agent Engine, Memory Bank
    "run.googleapis.com",              # Cloud Run hosting
    "cloudbuild.googleapis.com",       # CI/CD + source builds
    "artifactregistry.googleapis.com", # container images
    "secretmanager.googleapis.com",    # secrets
    "cloudtrace.googleapis.com",       # distributed tracing
    "logging.googleapis.com",          # structured logs
    "monitoring.googleapis.com",
    "iam.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  service            = each.value
  disable_on_destroy = false
}

# ---------- Runtime service account (least privilege) ----------
resource "google_service_account" "agent" {
  account_id   = "park-concierge-sa"
  display_name = "Desert Peaks concierge runtime"
  depends_on   = [google_project_service.apis]
}

locals {
  agent_roles = [
    "roles/aiplatform.user",              # call Gemini, Agent Engine sessions + memory
    "roles/logging.logWriter",            # write structured logs
    "roles/cloudtrace.agent",             # export OpenTelemetry spans
    "roles/monitoring.metricWriter",
    "roles/secretmanager.secretAccessor", # read secrets at runtime
  ]
}

resource "google_project_iam_member" "agent_roles" {
  for_each = toset(local.agent_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.agent.email}"
}

# ---------- Secret Manager (no hardcoded keys) ----------
# Holds an optional AI Studio key for non-Vertex environments. Add the value with:
#   printf '%s' "$KEY" | gcloud secrets versions add gemini-api-key --data-file=-
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# ---------- CI/CD permissions for the Cloud Build service account ----------
locals {
  build_sa = "serviceAccount:${data.google_project.this.number}-compute@developer.gserviceaccount.com"
  build_roles = [
    "roles/run.admin",                  # deploy Cloud Run
    "roles/iam.serviceAccountUser",     # run the service as park-concierge-sa
    "roles/aiplatform.user",            # run the eval gate against Gemini
    "roles/artifactregistry.writer",    # push images
    "roles/storage.admin",              # source uploads
    "roles/cloudbuild.builds.builder",
    "roles/logging.logWriter",
  ]
}

resource "google_project_iam_member" "build_roles" {
  for_each   = toset(local.build_roles)
  project    = var.project_id
  role       = each.value
  member     = local.build_sa
  depends_on = [google_project_service.apis]
}
