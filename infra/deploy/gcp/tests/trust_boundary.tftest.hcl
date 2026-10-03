# The trust boundary on Cloud Run (ADR-0004, ADR-0015): who can read which secret, spelled out
# here independently of iam.tf, so changing a grant means changing this test on purpose. The
# GCP counterpart of the compose check in docs/deployment.md, section 3.

mock_provider "google" {
  source = "./tests/mocks/google"
}

mock_provider "google-beta" {
  source = "./tests/mocks/google-beta"
}

variables {
  project_id           = "pb-test-project"
  github_repository    = "someone/pattern-blue-gcp"
  github_repository_id = "123456"
  iap_members          = ["user:someone@example.com"]
}

run "secret_access_is_exactly_the_compose_matrix" {
  command = apply

  assert {
    condition = toset([
      for grant in google_secret_manager_secret_iam_member.access :
      "${trimsuffix(trimprefix(grant.member, "serviceAccount:"), "@pb-test-project.iam.gserviceaccount.com")} ${grant.secret_id}"
      ]) == toset([
      "pb-banking-core pb-database-url",
      "pb-banking-core pb-redis-core-url",
      "pb-banking-core pb-master-key",
      "pb-banking-core pb-blind-index-salt",
      "pb-banking-core pb-admin-api-token",
      "pb-orchestrator pb-redis-edge-url",
      "pb-orchestrator pb-session-secret",
      "pb-orchestrator pb-agent-api-token",
      "pb-orchestrator pb-llm-api-key",
      "pb-web-backoffice pb-admin-api-token",
      "pb-web-backoffice pb-agent-api-token",
      "pb-web-backoffice pb-backoffice-session-secret",
      "pb-web-backoffice pb-demo-agent-password",
      "pb-web-backoffice pb-demo-judge-accounts",
      "pb-migrate pb-database-url",
      "pb-seed pb-database-url",
      "pb-seed pb-master-key",
      "pb-seed pb-blind-index-salt",
    ])
    error_message = "The secret grants are not the compose matrix."
  }

  assert {
    condition     = alltrue([for grant in google_secret_manager_secret_iam_member.access : grant.role == "roles/secretmanager.secretAccessor"])
    error_message = "Every grant is read-only access to one secret."
  }
}

run "untrusted_services_never_see_core_credentials" {
  command = apply

  # By name, secret or plain: the orchestrator, the model server and the customer web client
  # receive no database URL, core Redis, key or salt.
  assert {
    condition = alltrue(flatten([
      for name in ["orchestrator", "encoder", "web-client"] : [
        for env in google_cloud_run_v2_service.svc[name].template[0].containers[0].env :
        !contains(["DATABASE_URL", "MASTER_KEY", "BLIND_INDEX_SALT", "POSTGRES_PASSWORD", "ADMIN_API_TOKEN"], env.name)
      ]
    ]))
    error_message = "An untrusted service receives a core credential."
  }

  # The orchestrator's only Redis is redis-edge.
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["orchestrator"].template[0].containers[0].env :
      env.value_source[0].secret_key_ref[0].secret if env.name == "REDIS_URL"
    ]) == "pb-redis-edge-url"
    error_message = "The orchestrator's REDIS_URL must be redis-edge."
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["banking-core"].template[0].containers[0].env :
      env.value_source[0].secret_key_ref[0].secret if env.name == "REDIS_URL"
    ]) == "pb-redis-core-url"
    error_message = "banking-core's REDIS_URL must be redis-core."
  }

  # The netcheck job, which runs untrusted code paths in the edge zone, holds no secret.
  assert {
    condition     = length([for env in google_cloud_run_v2_job.job["netcheck"].template[0].template[0].containers[0].env : env if length(env.value_source) > 0]) == 0
    error_message = "The netcheck job must hold no secret."
  }
}

run "each_workload_runs_as_its_own_service_account" {
  command = apply

  assert {
    condition = alltrue([
      for name, service in google_cloud_run_v2_service.svc :
      service.template[0].service_account == "pb-${name}@pb-test-project.iam.gserviceaccount.com"
    ])
    error_message = "A service does not run as its own service account."
  }

  assert {
    condition = alltrue([
      for name, job in google_cloud_run_v2_job.job :
      job.template[0].template[0].service_account == "pb-${name}@pb-test-project.iam.gserviceaccount.com"
    ])
    error_message = "A job does not run as its own service account."
  }
}

run "the_llm_key_never_enters_the_state" {
  command = apply

  assert {
    condition     = !contains(keys(google_secret_manager_secret_version.value), "llm-api-key")
    error_message = "Terraform must not write a version of the LLM key."
  }

  assert {
    condition     = contains(keys(google_secret_manager_secret.secret), "llm-api-key")
    error_message = "The LLM key's secret container must exist for `make gcp-llm-key`."
  }
}
