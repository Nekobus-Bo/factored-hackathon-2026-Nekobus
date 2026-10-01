# State lives in a GCS bucket created once by `make gcp-state`, outside Terraform (it has
# to exist before the first init). Bucket and prefix come from `make gcp-init`. The state
# holds every generated secret: the bucket is private, versioned and team-only (ADR-0015).
terraform {
  backend "gcs" {}
}
