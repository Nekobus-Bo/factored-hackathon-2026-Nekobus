# The embedding model is pinned in two places that must agree: .env.example, which deploy.yml
# reads to bake the weights into the encoder image, and the variables Terraform gives the
# encoder and banking-core at runtime. A mismatch makes kb.search unavailable in production.

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

run "the_runtime_pins_match_the_baked_ones" {
  command = apply

  assert {
    condition = alltrue([
      for name, value in {
        EMBEDDING_MODEL          = var.embedding_model
        EMBEDDING_REVISION       = var.embedding_revision
        EMBEDDING_WEIGHTS_SHA256 = var.embedding_weights_sha256
      } :
      one(regexall("(?m)^${name}=(.*)$", file("../../../.env.example")))[0] == value
    ])
    error_message = "The embedding pins in variables.tf and .env.example differ."
  }

  assert {
    condition = alltrue(flatten([
      for name in ["encoder", "banking-core"] : [
        for env in google_cloud_run_v2_service.svc[name].template[0].containers[0].env :
        env.value == var.embedding_revision if env.name == "EMBEDDING_REVISION"
      ]
    ]))
    error_message = "The encoder and banking-core must be given the same revision."
  }

  assert {
    condition = one([
      for env in google_cloud_run_v2_service.svc["encoder"].template[0].containers[0].env : env.value if env.name == "HF_HUB_OFFLINE"
    ]) == "1"
    error_message = "The encoder must never download: its weights are in the image."
  }
}

run "a_branch_is_not_a_pin" {
  command = plan

  variables {
    embedding_revision = "main"
  }

  expect_failures = [var.embedding_revision]
}
