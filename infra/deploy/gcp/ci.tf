# How deploy.yml logs in to GCP: GitHub's OIDC token, exchanged through Workload Identity
# Federation for the deployer service account (ADR-0015). GitHub holds no GCP secret.
#
# The provider accepts a token only from one repository (by id), on main, from deploy.yml.
# The deployer can push images, roll the services and jobs to a new image, run the jobs and
# read logs; it can change nothing else Terraform manages.
locals {
  deploy_workflow_ref = "${var.github_repository}/.github/workflows/deploy.yml@refs/heads/main"
  deployer_email      = "${google_service_account.deployer.account_id}@${var.project_id}.iam.gserviceaccount.com"
  github_principals   = "principalSet://iam.googleapis.com/projects/${data.google_project.this.number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github.workload_identity_pool_id}/attribute.repository_id/${var.github_repository_id}"
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "${var.name_prefix}-github"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "${var.name_prefix}-github-oidc"
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"          = "assertion.sub"
    "attribute.repository"    = "assertion.repository"
    "attribute.repository_id" = "assertion.repository_id"
    "attribute.ref"           = "assertion.ref"
    "attribute.workflow_ref"  = "assertion.workflow_ref"
  }

  attribute_condition = join(" && ", [
    "assertion.repository_id == \"${var.github_repository_id}\"",
    "assertion.ref == \"refs/heads/main\"",
    "assertion.workflow_ref == \"${local.deploy_workflow_ref}\"",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  account_id   = "${var.name_prefix}-deployer"
  display_name = "Pattern Blue deploy.yml"

  depends_on = [google_project_service.api]
}

resource "google_service_account_iam_member" "deployer_federation" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${local.deployer_email}"
  role               = "roles/iam.workloadIdentityUser"
  member             = local.github_principals
}

resource "google_artifact_registry_repository_iam_member" "deployer_push" {
  repository = google_artifact_registry_repository.images.name
  location   = google_artifact_registry_repository.images.location
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${local.deployer_email}"
}

# Update services and jobs, run jobs, and read what they logged when a deploy fails.
resource "google_project_iam_member" "deployer" {
  for_each = toset(["roles/run.developer", "roles/logging.viewer"])

  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${local.deployer_email}"
}

# A new revision runs as its service's own account: the deployer may act as each of them.
resource "google_service_account_iam_member" "deployer_acts_as" {
  for_each = local.service_account_email

  service_account_id = "projects/${var.project_id}/serviceAccounts/${each.value}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.deployer_email}"
}

output "github_variables" {
  description = "The repository variables deploy.yml reads; `make gcp-gh-vars` sets them."
  value = {
    GCP_PROJECT_ID   = var.project_id
    GCP_REGION       = var.region
    GCP_WIF_PROVIDER = google_iam_workload_identity_pool_provider.github.name
    GCP_DEPLOYER_SA  = local.deployer_email
    GCP_REGISTRY     = local.image_registry
    GCP_NAME_PREFIX  = var.name_prefix
  }
}
