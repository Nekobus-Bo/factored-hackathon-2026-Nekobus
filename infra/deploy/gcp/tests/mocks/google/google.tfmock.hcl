# Values a real apply computes, where the provider validates their shape. Everything else is
# the mock's random placeholder. Shared by every test through `mock_provider ... source`.

mock_data "google_project" {
  defaults = {
    number = "123456789012"
  }
}

mock_resource "google_compute_network" {
  defaults = {
    id        = "projects/pb-test-project/global/networks/pb-vpc"
    self_link = "https://www.googleapis.com/compute/v1/projects/pb-test-project/global/networks/pb-vpc"
  }
}

mock_resource "google_sql_database_instance" {
  defaults = {
    private_ip_address = "10.20.0.3"
  }
}

mock_resource "google_redis_instance" {
  defaults = {
    host        = "10.20.1.4"
    port        = 6379
    auth_string = "mock-auth-string"
  }
}

mock_resource "google_secret_manager_secret" {
  defaults = {
    id = "projects/pb-test-project/secrets/pb-mock"
  }
}

# Every service lists every deterministic URL, so check.service_urls compares real values.
mock_resource "google_cloud_run_v2_service" {
  defaults = {
    urls = [
      "https://pb-banking-core-123456789012.us-east1.run.app",
      "https://pb-encoder-123456789012.us-east1.run.app",
      "https://pb-orchestrator-123456789012.us-east1.run.app",
      "https://pb-web-backoffice-123456789012.us-east1.run.app",
      "https://pb-web-client-123456789012.us-east1.run.app",
    ]
  }
}
