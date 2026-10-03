# Sizing, billing and the two switches (warm, services_enabled), plus what the services must
# not be given.

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

run "only_the_model_server_bills_as_always_on" {
  command = apply

  assert {
    condition     = [for name, service in google_cloud_run_v2_service.svc : name if !service.template[0].containers[0].resources[0].cpu_idle] == ["encoder"]
    error_message = "cpu_idle must be false for the encoder only; anything else bills as always-on."
  }
}

run "ports_and_timeouts" {
  command = apply

  assert {
    condition = alltrue([
      for name, port in { "banking-core" = 8081, "encoder" = 8090, "orchestrator" = 8080, "web-client" = 8080, "web-backoffice" = 8080 } :
      google_cloud_run_v2_service.svc[name].template[0].containers[0].ports[0].container_port == port
    ])
    error_message = "A service listens on the wrong port (the Python images hardcode theirs)."
  }

  # Cloud Run reserves PORT and sets it to container_port.
  assert {
    condition = alltrue(concat(
      flatten([for service in google_cloud_run_v2_service.svc : [for env in service.template[0].containers[0].env : env.name != "PORT"]]),
      flatten([for job in google_cloud_run_v2_job.job : [for env in job.template[0].template[0].containers[0].env : env.name != "PORT"]]),
    ))
    error_message = "PORT must never be set."
  }

  assert {
    condition     = google_cloud_run_v2_service.svc["orchestrator"].template[0].timeout == "600s"
    error_message = "The orchestrator needs 600 s for a worst-case turn."
  }
}

run "warm_keeps_the_backends_running" {
  command = apply

  assert {
    condition = alltrue([
      for name in ["banking-core", "encoder", "orchestrator"] :
      google_cloud_run_v2_service.svc[name].template[0].scaling[0].min_instance_count == 1
    ])
    error_message = "warm = true keeps one instance of each backend."
  }

  assert {
    condition     = google_cloud_run_v2_service.svc["encoder"].template[0].scaling[0].max_instance_count == 1
    error_message = "The model server has one replica (docs/limitations.md)."
  }
}

run "not_warm_scales_everything_to_zero" {
  command = apply

  variables {
    warm = false
  }

  assert {
    condition     = alltrue([for service in google_cloud_run_v2_service.svc : service.template[0].scaling[0].min_instance_count == 0])
    error_message = "warm = false scales every service to zero."
  }
}

run "the_first_apply_creates_no_service_or_job" {
  command = apply

  variables {
    services_enabled = false
  }

  assert {
    condition     = length(google_cloud_run_v2_service.svc) == 0 && length(google_cloud_run_v2_job.job) == 0
    error_message = "services_enabled = false creates no Cloud Run service or job."
  }

  assert {
    condition     = length(google_secret_manager_secret.secret) == 12 && length(google_redis_instance.zone) == 2
    error_message = "Everything else is created by the first apply."
  }
}

run "the_seed_can_run_in_production" {
  command = apply

  assert {
    condition     = contains(google_cloud_run_v2_job.job["seed"].template[0].template[0].containers[0].command, "--force")
    error_message = "The seed refuses APP_ENV=production without --force."
  }

  assert {
    condition     = google_cloud_run_v2_job.job["seed"].template[0].template[0].max_retries == 0
    error_message = "A failed seed must not run again by itself: it truncates tables."
  }
}
