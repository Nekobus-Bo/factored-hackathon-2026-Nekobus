# What `make gcp-gh-vars`, `make gcp-smoke` and the runbook read after an apply.

output "project_id" {
  description = "The GCP project."
  value       = var.project_id
}

output "project_number" {
  description = "The GCP project number (part of the Cloud Run service URLs)."
  value       = data.google_project.this.number
}

output "region" {
  description = "The region of every regional resource."
  value       = var.region
}

output "llm_api_key_secret" {
  description = "The secret that holds the LLM key; add its value with `make gcp-llm-key`."
  value       = google_secret_manager_secret.secret["llm-api-key"].secret_id
}

output "demo_agent_password_secret" {
  description = "The secret that holds the back office's demo password (read it with gcloud secrets versions access)."
  value       = google_secret_manager_secret.secret["demo-agent-password"].secret_id
}
