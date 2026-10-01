# The compose networks, on a VPC (ADR-0015). Every Cloud Run service and job leaves through
# Direct VPC egress with all traffic routed into the VPC, on one of three subnets:
#
#   core    banking-core, migrate, seed. No NAT: nothing reaches the internet, as the
#           compose `core` network (internal: true).
#   edge    encoder, web-client, web-backoffice. No NAT either: the model server receives
#           raw customer text and has no path out.
#   egress  the orchestrator alone, with Cloud NAT for the LLM provider.
#
# Private Google Access lets every subnet reach Google APIs and the internal run.app URLs
# without NAT. Tags select the firewall rules: pb-core on core, pb-edge on edge and egress.
#
# Cloud SQL and redis-core sit in the psa-core range, redis-edge in psa-edge. The ranges are
# fixed, so the deny rules below name them at plan time and a test can check them offline.
locals {
  subnets = {
    core   = { cidr = "10.10.0.0/24", tag = "${var.name_prefix}-core" }
    edge   = { cidr = "10.10.1.0/24", tag = "${var.name_prefix}-edge" }
    egress = { cidr = "10.10.2.0/24", tag = "${var.name_prefix}-edge" }
  }

  psa_ranges = {
    core = { address = "10.20.0.0", prefix_length = 20 }
    edge = { address = "10.21.0.0", prefix_length = 24 }
  }

  core_tag = "${var.name_prefix}-core"
  edge_tag = "${var.name_prefix}-edge"
}

resource "google_compute_network" "vpc" {
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.api]
}

resource "google_compute_subnetwork" "subnet" {
  for_each = local.subnets

  name                     = "${var.name_prefix}-${each.key}"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = each.value.cidr
  private_ip_google_access = true
}

# NAT for the egress subnet only: LIST_OF_SUBNETWORKS leaves core and edge without it.
resource "google_compute_router" "egress" {
  name    = "${var.name_prefix}-egress"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "egress" {
  name                               = "${var.name_prefix}-egress"
  region                             = var.region
  router                             = google_compute_router.egress.name
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.subnet["egress"].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# Private service access for Cloud SQL and Memorystore. ABANDON: after a Cloud SQL instance is
# deleted the connection cannot be removed for days; tear the environment down by deleting
# the project.
resource "google_compute_global_address" "psa" {
  for_each = local.psa_ranges

  name          = "${var.name_prefix}-psa-${each.key}"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  address       = each.value.address
  prefix_length = each.value.prefix_length
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [for range in google_compute_global_address.psa : range.name]
  deletion_policy         = "ABANDON"
}

# The trust boundary: nothing tagged edge reaches Postgres or redis-core (ADR-0004,
# ADR-0006). Priority 900 wins over the implied allow-all egress.
resource "google_compute_firewall" "deny_edge_to_core_data" {
  name               = "${var.name_prefix}-deny-edge-to-core-data"
  network            = google_compute_network.vpc.id
  direction          = "EGRESS"
  priority           = 900
  target_tags        = [local.edge_tag]
  destination_ranges = ["${local.psa_ranges.core.address}/${local.psa_ranges.core.prefix_length}"]

  deny {
    protocol = "all"
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

# And the core zone has no business with redis-edge.
resource "google_compute_firewall" "deny_core_to_edge_data" {
  name               = "${var.name_prefix}-deny-core-to-edge-data"
  network            = google_compute_network.vpc.id
  direction          = "EGRESS"
  priority           = 900
  target_tags        = [local.core_tag]
  destination_ranges = ["${local.psa_ranges.edge.address}/${local.psa_ranges.edge.prefix_length}"]

  deny {
    protocol = "all"
  }

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}
