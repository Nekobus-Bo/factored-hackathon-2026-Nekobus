# Every secret the services read, in Secret Manager (ADR-0015). Terraform generates the random
# ones and assembles the connection URLs; the LLM key is created empty and added by hand
# (`make gcp-llm-key`), so it never enters the state. The rest is in the state: the state
# bucket is as sensitive as these values.
locals {
  generated_secrets = toset([
    "admin-api-token",
    "agent-api-token",
    "backoffice-session-secret",
    "blind-index-salt",
    "demo-agent-password",
    "master-key",
    "session-secret",
  ])

  composed_secrets = toset(["database-url", "demo-judge-accounts", "redis-core-url", "redis-edge-url"])
  manual_secrets   = toset(["llm-api-key"])

  # The secrets Terraform writes a version for. The set is keyed by name, never by value.
  written_secrets = setunion(local.generated_secrets, local.composed_secrets)
  all_secrets     = setunion(local.written_secrets, local.manual_secrets)

  # judge1 to judgeN at the demo agent's domain (ADR-0015, amendment of 2026-10-03). Keyed by
  # e-mail, so adding a judge leaves the others' passwords as they were.
  judge_emails = [
    for n in range(1, var.judge_accounts + 1) : "judge${n}@${split("@", var.demo_agent_email)[1]}"
  ]

  redis_urls = {
    for zone, instance in google_redis_instance.zone :
    "redis-${zone}-url" => "redis://:${urlencode(instance.auth_string)}@${instance.host}:${instance.port}/0"
  }

  secret_values = merge(
    { for name in local.generated_secrets : name => random_password.generated[name].result },
    local.redis_urls,
    {
      # sslmode=require: the instance accepts encrypted connections only (data.tf).
      "database-url" = format(
        "postgresql+psycopg://%s:%s@%s:5432/%s?sslmode=require",
        google_sql_user.app.name,
        random_password.db.result,
        google_sql_database_instance.bank.private_ip_address,
        google_sql_database.bank.name,
      )
      # The back office's DEMO_EXTRA_AGENTS: e-mail to password, "{}" when there is no judge.
      "demo-judge-accounts" = jsonencode({ for email in local.judge_emails : email => random_password.judge[email].result })
    },
  )
}

# Letters and digits, 24 of them: typed by hand from a message, and well over the back
# office's 16-character floor for an extra login.
resource "random_password" "judge" {
  for_each = toset(local.judge_emails)

  length  = 24
  special = false
}

# The keys are derived with HKDF from these strings (ADR-0005), and the tokens are compared as
# strings: letters and digits keep them safe in environment variables and URLs.
resource "random_password" "generated" {
  for_each = local.generated_secrets

  length  = 48
  special = false
}

resource "google_secret_manager_secret" "secret" {
  for_each = local.all_secrets

  secret_id = "${var.name_prefix}-${each.key}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.api]
}

resource "google_secret_manager_secret_version" "value" {
  for_each = local.written_secrets

  secret      = google_secret_manager_secret.secret[each.key].id
  secret_data = local.secret_values[each.key]
}
