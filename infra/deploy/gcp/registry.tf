# Where deploy.yml pushes the five images, tagged sha-<commit>. Cloud Run pulls from here.
resource "google_artifact_registry_repository" "images" {
  repository_id = "pattern-blue"
  location      = var.region
  format        = "DOCKER"
  description   = "Pattern Blue application images (ADR-0015)."

  depends_on = [google_project_service.api]
}

locals {
  image_registry = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "image_registry" {
  description = "Image path prefix: <image_registry>/<service>:<tag>."
  value       = local.image_registry
}
