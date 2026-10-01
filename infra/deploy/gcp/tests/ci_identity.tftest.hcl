# How deploy.yml logs in (ADR-0015): only one repository, on main, from deploy.yml; and the
# deployer can roll images out but not reshape the environment.

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

run "the_login_is_bound_to_one_repository_branch_and_workflow" {
  command = apply

  assert {
    condition     = google_iam_workload_identity_pool_provider.github.attribute_condition == "assertion.repository_id == \"123456\" && assertion.ref == \"refs/heads/main\" && assertion.workflow_ref == \"someone/pattern-blue-gcp/.github/workflows/deploy.yml@refs/heads/main\""
    error_message = "The provider must accept only this repository id, main and deploy.yml."
  }

  assert {
    condition     = google_iam_workload_identity_pool_provider.github.oidc[0].issuer_uri == "https://token.actions.githubusercontent.com"
    error_message = "The issuer must be GitHub Actions."
  }

  assert {
    condition     = endswith(google_service_account_iam_member.deployer_federation.member, "/attribute.repository_id/123456")
    error_message = "Only this repository may impersonate the deployer."
  }
}

run "the_deployer_rolls_out_and_nothing_more" {
  command = apply

  assert {
    condition     = toset([for grant in google_project_iam_member.deployer : grant.role]) == toset(["roles/run.developer", "roles/logging.viewer"])
    error_message = "The deployer's project roles are run.developer and logging.viewer."
  }

  assert {
    condition     = google_artifact_registry_repository_iam_member.deployer_push.role == "roles/artifactregistry.writer"
    error_message = "The deployer pushes images to the one repository."
  }

  assert {
    condition = toset(keys(google_service_account_iam_member.deployer_acts_as)) == toset([
      "banking-core", "encoder", "migrate", "netcheck", "orchestrator", "seed", "web-backoffice", "web-client",
    ])
    error_message = "The deployer may act as each runtime service account, to deploy revisions that run as it."
  }
}

run "a_malformed_repository_is_refused" {
  command = plan

  variables {
    github_repository = "not-a-repository"
  }

  expect_failures = [var.github_repository]
}

run "a_repository_name_is_not_an_id" {
  command = plan

  variables {
    github_repository_id = "someone/pattern-blue-gcp"
  }

  expect_failures = [var.github_repository_id]
}
