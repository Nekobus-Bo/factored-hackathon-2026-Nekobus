# Detective mode on Cloud Run (ADR-0019): off unless the variable is set, and it reaches only
# the orchestrator. presentation.tfvars sets it (terraform test does not read var files).

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
}

run "off_by_default" {
  command = apply

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["orchestrator"].template[0].containers[0].env :
      env.value if env.name == "DETECTIVE_MODE"
    ]) == "false"
    error_message = "Without detective_mode the orchestrator does not offer detective mode."
  }
}

run "on_reaches_only_the_orchestrator" {
  command = apply

  variables {
    detective_mode = true
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["orchestrator"].template[0].containers[0].env :
      env.value if env.name == "DETECTIVE_MODE"
    ]) == "true"
    error_message = "detective_mode = true must reach the orchestrator."
  }

  assert {
    condition = alltrue([
      for name, service in google_cloud_run_v2_service.svc :
      !contains([for env in service.template[0].containers[0].env : env.name], "DETECTIVE_MODE")
      if name != "orchestrator"
    ])
    error_message = "Only the orchestrator reads DETECTIVE_MODE."
  }
}
