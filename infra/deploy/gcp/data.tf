# The data layer (ADR-0006 on Cloud Run, ADR-0015): one PostgreSQL and one Redis per trust
# zone, all on private addresses in the psa ranges of network.tf. Only banking-core and its
# jobs get the credentials (iam.tf), and only the core subnet can reach psa-core.

# PostgreSQL 16 and later default to the Enterprise Plus edition, which rejects the small
# shared-core tiers: the edition is set explicitly.
resource "google_sql_database_instance" "bank" {
  name                = "${var.name_prefix}-bank"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = var.data_deletion_protection

  settings {
    edition           = "ENTERPRISE"
    tier              = var.sql_tier
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    ip_configuration {
      ipv4_enabled       = false
      private_network    = google_compute_network.vpc.id
      allocated_ip_range = google_compute_global_address.psa["core"].name
      ssl_mode           = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled = true
    }
  }

  depends_on = [google_service_networking_connection.psa]
}

resource "google_sql_database" "bank" {
  name     = "bank"
  instance = google_sql_database_instance.bank.name
}

# Letters and digits only: the password goes into DATABASE_URL as it is.
resource "random_password" "db" {
  length  = 40
  special = false
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.bank.name
  password = random_password.db.result
}

# One Memorystore per trust zone, each with AUTH, as the two compose containers with
# --requirepass. No TLS, as in compose (declared in docs/limitations.md).
locals {
  redis = {
    core = { range = "core" }
    edge = { range = "edge" }
  }
}

resource "google_redis_instance" "zone" {
  for_each = local.redis

  name                    = "${var.name_prefix}-redis-${each.key}"
  region                  = var.region
  tier                    = "BASIC"
  memory_size_gb          = 1
  redis_version           = "REDIS_7_2"
  authorized_network      = google_compute_network.vpc.id
  connect_mode            = "PRIVATE_SERVICE_ACCESS"
  reserved_ip_range       = google_compute_global_address.psa[each.value.range].name
  auth_enabled            = true
  transit_encryption_mode = "DISABLED"

  depends_on = [google_service_networking_connection.psa]
}
