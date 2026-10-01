mock_resource "google_project_service_identity" {
  defaults = {
    email = "service-123456789012@gcp-sa-iap.iam.gserviceaccount.com"
  }
}
