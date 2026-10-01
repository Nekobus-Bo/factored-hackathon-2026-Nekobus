# One-off tasks as Cloud Run Jobs (ADR-0015). migrate and seed run the banking-core image in
# the core zone, as the compose services of the same name; deploy.yml runs migrate before it
# rolls banking-core out, and seed when DEMO_SEED is true. netcheck runs the orchestrator image
# in the edge zone and proves the firewall of network.tf on the real network.
#
# As for the services, Terraform creates them on bootstrap_image and deploy.yml owns the image.
locals {
  jobs = {
    "migrate" = {
      image   = "banking-core"
      command = ["alembic", "-c", "apps/banking-core/alembic.ini", "upgrade", "head"]
      memory  = "1Gi"
      timeout = "600s"
      subnet  = "core"
      env     = { APP_ENV = "production" }
    }

    # --force: the seed refuses APP_ENV=production without it. It truncates and reloads the
    # banking tables with the synthetic demo customers. /tmp is the job's scratch space.
    "seed" = {
      image   = "banking-core"
      command = ["python", "-m", "banking_core.seed.cli", "seed", "--force", "--raw-dir", "/tmp/raw"]
      memory  = "2Gi"
      timeout = "1800s"
      subnet  = "core"
      env     = { APP_ENV = "production" }
    }

    "netcheck" = {
      image   = "orchestrator"
      command = ["python", "-c", file("${path.module}/netcheck.py")]
      memory  = "512Mi"
      timeout = "120s"
      subnet  = "edge"
      env = {
        NETCHECK_BLOCKED = join(",", [
          "${google_sql_database_instance.bank.private_ip_address}:5432",
          "${google_redis_instance.zone["core"].host}:${google_redis_instance.zone["core"].port}",
        ])
        NETCHECK_ALLOWED = "${google_redis_instance.zone["edge"].host}:${google_redis_instance.zone["edge"].port}"
      }
    }
  }

  enabled_jobs = var.services_enabled ? local.jobs : {}
}

resource "google_cloud_run_v2_job" "job" {
  for_each = local.enabled_jobs

  name                = "${var.name_prefix}-${each.key}"
  location            = var.region
  deletion_protection = false

  labels = {
    app       = "pattern-blue"
    component = each.key
  }

  template {
    task_count = 1

    template {
      service_account = local.service_account_email[each.key]
      timeout         = each.value.timeout
      max_retries     = 0

      vpc_access {
        egress = "ALL_TRAFFIC"

        network_interfaces {
          network    = google_compute_network.vpc.id
          subnetwork = google_compute_subnetwork.subnet[each.value.subnet].id
          tags       = [local.subnets[each.value.subnet].tag]
        }
      }

      containers {
        image   = var.bootstrap_image
        command = each.value.command

        resources {
          limits = {
            cpu    = "1"
            memory = each.value.memory
          }
        }

        dynamic "env" {
          for_each = each.value.env

          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = local.identity_secrets[each.key]

          content {
            name = env.key

            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.secret[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.access,
    google_secret_manager_secret_version.value,
  ]
}

output "jobs" {
  description = "Each job and the image deploy.yml gives it."
  value       = { for name, job in local.enabled_jobs : "${var.name_prefix}-${name}" => job.image }
}
