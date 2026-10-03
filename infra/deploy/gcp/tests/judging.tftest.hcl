# The judging window (ADR-0015, amendment of 2026-10-03): by default the back office stays
# behind IAP with no judge logins; backoffice_public opens it, judge_accounts adds the logins,
# and nothing else changes either way.

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
  iap_members          = ["user:someone@example.com", "group:team@example.com"]
}

run "by_default_the_back_office_is_closed_and_there_is_no_judge" {
  command = apply

  assert {
    condition     = google_cloud_run_v2_service.svc["web-backoffice"].iap_enabled && !google_cloud_run_v2_service.svc["web-backoffice"].invoker_iam_disabled
    error_message = "By default the back office stays behind IAP, with the invoker IAM check on."
  }

  assert {
    condition     = length(google_iap_web_cloud_run_service_iam_member.access) == 2
    error_message = "By default the listed members pass IAP."
  }

  assert {
    condition     = length(random_password.judge) == 0 && nonsensitive(google_secret_manager_secret_version.value["demo-judge-accounts"].secret_data) == "{}"
    error_message = "By default there is no judge login, and the back office reads an empty object."
  }
}

run "open_drops_iap_and_lets_anyone_invoke_the_back_office" {
  command = apply

  variables {
    backoffice_public = true
  }

  assert {
    condition     = !google_cloud_run_v2_service.svc["web-backoffice"].iap_enabled
    error_message = "Open, the back office has no IAP."
  }

  assert {
    condition     = google_cloud_run_v2_service.svc["web-backoffice"].invoker_iam_disabled
    error_message = "Open, anyone may invoke the back office, like the customer app."
  }

  assert {
    condition     = length(google_cloud_run_v2_service_iam_member.iap_invoker) == 0 && length(google_iap_web_cloud_run_service_iam_member.access) == 0
    error_message = "Open, no IAP invoker or IAP member binding is left behind."
  }

  assert {
    condition     = google_cloud_run_v2_service.svc["web-backoffice"].ingress == "INGRESS_TRAFFIC_ALL"
    error_message = "Opening changes who passes, not the ingress."
  }
}

run "open_changes_nothing_but_the_back_office" {
  command = apply

  variables {
    backoffice_public = true
  }

  assert {
    condition = alltrue([
      for name in ["banking-core", "encoder", "orchestrator"] :
      google_cloud_run_v2_service.svc[name].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    ])
    error_message = "The backends stay internal while the back office is open."
  }

  assert {
    condition = alltrue([
      for name, service in google_cloud_run_v2_service.svc :
      !service.iap_enabled if name != "web-backoffice"
    ])
    error_message = "No other service gains or loses IAP."
  }
}

run "judge_accounts_are_judge1_to_judgeN_at_the_demo_domain" {
  command = apply

  variables {
    judge_accounts = 3
  }

  assert {
    condition     = sort(keys(random_password.judge)) == tolist(["judge1@demo.local", "judge2@demo.local", "judge3@demo.local"])
    error_message = "Three judges are judge1 to judge3 at the demo agent's domain."
  }

  assert {
    condition     = alltrue([for password in random_password.judge : password.length == 24 && !password.special])
    error_message = "Each judge password is 24 letters and digits."
  }

  assert {
    condition = (
      sort(keys(jsondecode(nonsensitive(google_secret_manager_secret_version.value["demo-judge-accounts"].secret_data))))
      == tolist(["judge1@demo.local", "judge2@demo.local", "judge3@demo.local"])
    )
    error_message = "The back office's DEMO_EXTRA_AGENTS holds exactly the judges."
  }

  assert {
    condition     = google_cloud_run_v2_service.svc["web-backoffice"].iap_enabled
    error_message = "Judge logins alone do not open the back office."
  }
}

run "the_judge_domain_follows_the_demo_agent" {
  command = apply

  variables {
    judge_accounts   = 1
    demo_agent_email = "agent@bank.example"
  }

  assert {
    condition     = keys(random_password.judge) == ["judge1@bank.example"]
    error_message = "A judge's e-mail uses the demo agent's domain."
  }
}

run "the_back_office_reads_the_judge_logins_at_a_pinned_version" {
  command = apply

  variables {
    judge_accounts = 2
  }

  # A new version of a secret read as "latest" reaches no running instance; a pinned one is a
  # change to the revision template, so the judge logins roll out when they change.
  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["web-backoffice"].template[0].containers[0].env :
      env.value_source[0].secret_key_ref[0].version if env.name == "DEMO_EXTRA_AGENTS"
    ]) == google_secret_manager_secret_version.value["demo-judge-accounts"].version
    error_message = "DEMO_EXTRA_AGENTS must read the version Terraform wrote."
  }

  assert {
    condition = alltrue([
      for env in google_cloud_run_v2_service.svc["web-backoffice"].template[0].containers[0].env :
      env.value_source[0].secret_key_ref[0].version == "latest" if length(env.value_source) > 0 && env.name != "DEMO_EXTRA_AGENTS"
    ])
    error_message = "Every other secret is still read as latest."
  }
}

run "judge_accounts_is_a_whole_number_up_to_20" {
  command = plan

  variables {
    judge_accounts = 21
  }

  expect_failures = [var.judge_accounts]
}
