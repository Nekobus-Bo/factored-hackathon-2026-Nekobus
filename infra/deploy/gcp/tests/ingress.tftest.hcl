# Who can reach what from outside (ADR-0013 on Cloud Run, ADR-0015): the backends accept
# internal traffic only, the customer app is public, the back office is behind IAP.

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

run "only_the_two_front_ends_are_reachable_from_the_internet" {
  command = apply

  assert {
    condition     = sort([for name, service in google_cloud_run_v2_service.svc : name if service.ingress == "INGRESS_TRAFFIC_ALL"]) == tolist(["web-backoffice", "web-client"])
    error_message = "Only web-client and web-backoffice may take traffic from the internet."
  }

  assert {
    condition = alltrue([
      for name in ["banking-core", "encoder", "orchestrator"] :
      google_cloud_run_v2_service.svc[name].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    ])
    error_message = "The backends must accept internal traffic only."
  }
}

run "the_back_office_is_behind_iap" {
  command = apply

  assert {
    condition     = google_cloud_run_v2_service.svc["web-backoffice"].iap_enabled
    error_message = "IAP must be on for the back office."
  }

  assert {
    condition     = !google_cloud_run_v2_service.svc["web-backoffice"].invoker_iam_disabled
    error_message = "The back office keeps the invoker IAM check, or IAP could be bypassed."
  }

  assert {
    condition     = keys(google_cloud_run_v2_service_iam_member.iap_invoker) == ["web-backoffice"]
    error_message = "Only the back office gets the IAP service agent as invoker."
  }

  assert {
    condition = (
      google_cloud_run_v2_service_iam_member.iap_invoker["web-backoffice"].role == "roles/run.invoker"
      && google_cloud_run_v2_service_iam_member.iap_invoker["web-backoffice"].member == "serviceAccount:service-123456789012@gcp-sa-iap.iam.gserviceaccount.com"
    )
    error_message = "The IAP service agent must be the back office's invoker."
  }

  assert {
    condition = (
      toset([for access in google_iap_web_cloud_run_service_iam_member.access : access.member]) == toset(var.iap_members)
      && alltrue([for access in google_iap_web_cloud_run_service_iam_member.access : access.role == "roles/iap.httpsResourceAccessor"])
    )
    error_message = "Exactly the listed members pass IAP."
  }
}

run "no_other_service_uses_iap_or_the_iam_check" {
  command = apply

  assert {
    condition = alltrue([
      for name in ["banking-core", "encoder", "orchestrator", "web-client"] :
      !google_cloud_run_v2_service.svc[name].iap_enabled && google_cloud_run_v2_service.svc[name].invoker_iam_disabled
    ])
    error_message = "The other services are called without identity tokens (ADR-0015): no IAP, invoker IAM check off."
  }
}

run "no_iap_members_means_nobody_passes" {
  command = apply

  variables {
    iap_members = []
  }

  assert {
    condition     = length(google_iap_web_cloud_run_service_iam_member.access) == 0
    error_message = "With no members, nobody is granted IAP access."
  }
}

run "an_iap_member_needs_a_type" {
  command = plan

  variables {
    iap_members = ["someone@example.com"]
  }

  expect_failures = [var.iap_members]
}
