# One service account per service and job, and exactly the secrets each one reads, as
# environment variable => secret. This map is the trust boundary on Cloud Run: it mirrors the
# per-service `environment:` blocks of infra/compose/docker-compose.yml (ADR-0004, ADR-0015).
# The orchestrator, the model server and the customer web client never hold database
# credentials, the core Redis or an encryption key; tests/trust_boundary.tftest.hcl checks it.
locals {
  identity_secrets = {
    "banking-core" = {
      DATABASE_URL     = "database-url"
      REDIS_URL        = "redis-core-url"
      MASTER_KEY       = "master-key"
      BLIND_INDEX_SALT = "blind-index-salt"
      ADMIN_API_TOKEN  = "admin-api-token"
    }
    "orchestrator" = {
      REDIS_URL       = "redis-edge-url"
      SESSION_SECRET  = "session-secret"
      AGENT_API_TOKEN = "agent-api-token"
      LLM_API_KEY     = "llm-api-key"
    }
    "encoder"    = {}
    "web-client" = {}
    "web-backoffice" = {
      ADMIN_API_TOKEN           = "admin-api-token"
      AGENT_API_TOKEN           = "agent-api-token"
      BACKOFFICE_SESSION_SECRET = "backoffice-session-secret"
      DEMO_AGENT_PASSWORD       = "demo-agent-password"
    }
    "migrate" = {
      DATABASE_URL = "database-url"
    }
    "seed" = {
      DATABASE_URL     = "database-url"
      MASTER_KEY       = "master-key"
      BLIND_INDEX_SALT = "blind-index-salt"
    }
    "netcheck" = {}
  }

  secret_access = {
    for pair in flatten([
      for identity, env in local.identity_secrets : [
        for secret in distinct(values(env)) : { identity = identity, secret = secret }
      ]
    ]) : "${pair.identity}/${pair.secret}" => pair
  }

  # Built from the account id rather than read back, so every grant is known at plan time.
  service_account_email = {
    for identity, account in google_service_account.runtime :
    identity => "${account.account_id}@${var.project_id}.iam.gserviceaccount.com"
  }
}

resource "google_service_account" "runtime" {
  for_each = local.identity_secrets

  account_id   = "${var.name_prefix}-${each.key}"
  display_name = "Pattern Blue ${each.key}"

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_iam_member" "access" {
  for_each = local.secret_access

  secret_id = google_secret_manager_secret.secret[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.service_account_email[each.value.identity]}"
}
