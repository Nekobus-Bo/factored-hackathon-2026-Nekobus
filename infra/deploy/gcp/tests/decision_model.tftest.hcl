# The decision model on Cloud Run is the one the local stack runs (ADR-0014, ADR-0015). The
# encoder's code default is the tfidf_lr artifact, so a missing DECISION_POINTS_FILE would
# quietly serve the baseline: the artifact must be named, and it must be the one .env.example
# names. Switching back to tfidf_lr is a variable, and both artifacts ship in the image.

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

run "the_encoder_serves_the_artifact_compose_runs" {
  command = apply

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["encoder"].template[0].containers[0].env : env.value if env.name == "DECISION_POINTS_FILE"
    ]) == one(regexall("(?m)^DECISION_POINTS_FILE=(.*)$", file("../../../.env.example")))[0]
    error_message = "The encoder must serve the decision-points artifact .env.example names."
  }

  assert {
    condition     = fileexists("../../../${var.decision_points_file}")
    error_message = "decision_points_file names an artifact that is not in the repository, so not in the image."
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["encoder"].template[0].containers[0].env : env.value if env.name == "OMP_NUM_THREADS"
    ]) == "2"
    error_message = "The encoder needs a fixed thread count for reproducible decisions (ADR-0012 E.4)."
  }
}

run "the_kill_switch_is_a_variable" {
  command = apply

  variables {
    decision_points_file = "packages/encoder/calibration/decision_points.json"
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["encoder"].template[0].containers[0].env : env.value if env.name == "DECISION_POINTS_FILE"
    ]) == "packages/encoder/calibration/decision_points.json"
    error_message = "decision_points_file must reach the encoder unchanged."
  }

  assert {
    condition     = fileexists("../../../${var.decision_points_file}")
    error_message = "The tfidf_lr artifact must be in the repository, so in the image."
  }
}

run "the_shipped_modes_apply_unless_overridden" {
  command = apply

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["orchestrator"].template[0].containers[0].env : env.value if env.name == "DECISION_POINTS_MODES"
    ]) == ""
    error_message = "By default the orchestrator must run the modes of decision_effects.yaml."
  }
}

run "the_mode_kill_switch_reaches_the_orchestrator" {
  command = apply

  variables {
    decision_points_modes = "intent_hint=shadow,clarify_route=shadow"
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["orchestrator"].template[0].containers[0].env : env.value if env.name == "DECISION_POINTS_MODES"
    ]) == "intent_hint=shadow,clarify_route=shadow"
    error_message = "decision_points_modes must reach the orchestrator unchanged."
  }
}

run "a_malformed_mode_override_is_rejected" {
  command = plan

  variables {
    decision_points_modes = "intent_hint=on"
  }

  expect_failures = [var.decision_points_modes]
}

run "only_artifacts_under_calibration" {
  command = plan

  variables {
    decision_points_file = "/etc/passwd"
  }

  expect_failures = [var.decision_points_file]
}
