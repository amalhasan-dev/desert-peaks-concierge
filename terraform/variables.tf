variable "project_id" {
  description = "Google Cloud project ID to deploy into."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Vertex AI."
  type        = string
  default     = "us-central1"
}
