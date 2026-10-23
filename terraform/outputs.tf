output "agent_service_account" {
  description = "Pass to Cloud Run with --service-account."
  value       = google_service_account.agent.email
}

output "secret_id" {
  value = google_secret_manager_secret.gemini_api_key.secret_id
}
