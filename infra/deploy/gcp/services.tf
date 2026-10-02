# The five Cloud Run services (ADR-0015). One map describes them; one resource creates them,
# so tests can assert on every service without a child module in the way.
#
# Settings mirror infra/compose/docker-compose.yml and its production overlay, service by
# service: the compose file is the reference, and a value set there is set here. PORT is
# never set: Cloud Run reserves it and sets it to container_port.
#
# deploy.yml owns the image. Terraform creates each service on bootstrap_image and ignores
# image changes afterwards.
locals {
  service_names = toset(["banking-core", "encoder", "orchestrator", "web-backoffice", "web-client"])

  # The deterministic URL, https://SERVICE-PROJECT_NUMBER.REGION.run.app: each service names
  # its upstreams without a cycle among the instances of one resource. check.service_urls
  # confirms after an apply that every service answers on it.
  service_url = {
    for name in local.service_names :
    name => "https://${var.name_prefix}-${name}-${data.google_project.this.number}.${var.region}.run.app"
  }

  min_instances = var.warm ? 1 : 0

  embedding_env = {
    EMBEDDING_MODEL    = var.embedding_model
    EMBEDDING_REVISION = var.embedding_revision
  }

  services = {
    # The model server. Receives raw customer text: internal only, and its subnet has no NAT.
    "encoder" = {
      port        = 8090
      cpu         = "2"
      memory      = "4Gi"
      cpu_idle    = false # always allocated: PyTorch should not be throttled between requests
      min         = local.min_instances
      max         = 1 # one replica (docs/limitations.md)
      concurrency = 8
      timeout     = "60s"
      ingress     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      iap         = false
      subnet      = "edge"
      startup     = "/ready"
      liveness    = "/health"
      env = merge(local.embedding_env, {
        APP_ENV                     = "production"
        LOG_LEVEL                   = "info"
        ENCODER_BACKEND             = "tfidf_lr"
        ENCODER_DEVICE              = "cpu"
        ENCODER_QUANTIZED           = "true"
        ABSTENTION_THRESHOLD        = "0.37"
        EMBEDDING_WEIGHTS_SHA256    = var.embedding_weights_sha256
        EMBEDDING_MAX_BATCH         = "64"
        DECISION_POINTS_FILE        = var.decision_points_file
        DECISION_POINTS_ALLOW_STALE = "false"
        # A fixed thread count keeps decisions reproducible (ADR-0012 E.4), as in compose.
        OMP_NUM_THREADS = "2"
        # The weights are baked into the image (apps/encoder/Dockerfile): never download.
        HF_HUB_OFFLINE = "1"
      })
    }

    # The trusted zone. /ready reads the policy config and builds the kb.search index through
    # the model server, so a revision that cannot reach either never takes traffic.
    "banking-core" = {
      port        = 8081
      cpu         = "1"
      memory      = "1Gi"
      cpu_idle    = true
      min         = local.min_instances
      max         = 2 # up to 15 database connections each
      concurrency = 20
      timeout     = "60s"
      ingress     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      iap         = false
      subnet      = "core"
      startup     = "/ready"
      liveness    = "/health"
      env = merge(local.embedding_env, {
        APP_ENV                                  = "production"
        LOG_LEVEL                                = "info"
        REDIS_SESSION_KEY_PREFIX                 = "session:"
        REDIS_OTP_CHALLENGE_KEY_PREFIX           = "otp:challenge:"
        REDIS_OTP_INBOX_KEY_PREFIX               = "otp:inbox:"
        REDIS_ATTEMPT_LIMIT_KEY_PREFIX           = "limit:"
        OTP_CHANNEL_MODE                         = "simulated"
        OTP_TTL_SECONDS                          = "300"
        OTP_MAX_ATTEMPTS                         = "3"
        OTP_MAX_RESENDS                          = "3"
        ALLOW_DEV_OTP_HOOK                       = "false"
        SESSION_TTL_SECONDS                      = "3600"
        DEFAULT_CURRENCY                         = "COP"
        POLICY_SEED_THRESHOLDS_MINOR             = jsonencode({ USD = 50000, EUR = 50000, BRL = 250000, COP = 200000000, ARS = 17795642 })
        POLICY_SEED_AMOUNT_MODE                  = "flag"
        POLICY_SEED_DISABLED_TOOLS               = "account.get_summary"
        ADMIN_API_ENABLED                        = "true" # the back office needs it
        DEMO_RESET_ENABLED                       = "true"
        TRANSACTION_LIST_MAX_LIMIT               = "50"
        RATE_LIMIT_ATTEMPTS_PER_SESSION          = "5"
        RATE_LIMIT_CUSTOMER_OTP_MAX_FAILURES     = "5"
        RATE_LIMIT_CUSTOMER_OTP_WINDOW_SECONDS   = "3600"
        RATE_LIMIT_CUSTOMER_OTP_LOCK_SECONDS     = "1800"
        RATE_LIMIT_DOCUMENT_MATCH_MAX_FAILURES   = "10"
        RATE_LIMIT_DOCUMENT_MATCH_WINDOW_SECONDS = "3600"
        SESSION_LOCK_TTL_MS                      = "10000"
        SESSION_LOCK_WAIT_MS                     = "2000"
        AUDIT_HASH_CHAIN_ENABLED                 = "true"
        RETRIEVAL_MODE                           = "vector"
        RETRIEVAL_TOP_K                          = "5"
        RETRIEVAL_SCORE_FLOOR                    = "0.80"
        EMBEDDING_BACKEND                        = "remote"
        MODEL_SERVER_URL                         = local.service_url["encoder"]
        # Compose uses 10 s; a cold model server on Cloud Run needs longer.
        MODEL_SERVER_TIMEOUT_SECONDS = "30"
      })
    }

    # The untrusted zone. The only subnet with NAT: it calls the LLM provider.
    "orchestrator" = {
      port        = 8080
      cpu         = "1"
      memory      = "1Gi"
      cpu_idle    = true
      min         = local.min_instances
      max         = 3
      concurrency = 40
      timeout     = "600s" # a worst-case turn is ~540 s (apps/orchestrator/src/orchestrator/config.py)
      ingress     = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      iap         = false
      subnet      = "egress"
      startup     = "/health"
      liveness    = "/health"
      env = {
        APP_ENV                              = "production"
        LOG_LEVEL                            = "info"
        BANKING_CORE_URL                     = local.service_url["banking-core"]
        ENCODER_URL                          = local.service_url["encoder"]
        ENCODER_ENABLED                      = "true"
        ENCODER_TIMEOUT_SECONDS              = "2"
        DECISION_POINTS_MODES                = var.decision_points_modes
        MAX_TOOL_ROUNDS                      = "5"
        REDIS_EDGE_KEY_PREFIX                = "orch:conv:"
        REDIS_EDGE_RATE_LIMIT_KEY_PREFIX     = "orch:ratelimit:"
        REDIS_EDGE_SESSION_INDEX_KEY_PREFIX  = "orch:session:"
        RATE_LIMIT_CONVERSATIONS_PER_IP_HOUR = tostring(var.rate_limit_conversations_per_ip_hour)
        TRUSTED_PROXY_HOPS                   = tostring(var.trusted_proxy_hops)
        AGENT_API_ENABLED                    = "true" # the back office needs it
        AGENT_LOCK_WAIT_SECONDS              = "10"
        SESSION_TTL_SECONDS                  = "3600"
        SESSION_LOCK_MARGIN_SECONDS          = "60"
        LLM_MODE                             = "live"
        LLM_MODEL                            = var.llm_model
        LLM_REASONING_EFFORT                 = var.llm_reasoning_effort
        LLM_TIMEOUT_SECONDS                  = "30"
        LLM_MAX_RETRIES                      = "2"
        LLM_REPLAY_ON_MISS                   = "fail"
        RETRIEVAL_MODE                       = "hybrid"
        RETRIEVAL_TOP_K                      = "5"
        RETRIEVAL_HYBRID_ALPHA               = "0.5"
        SUPPORTED_LOCALES                    = "es,pt,en"
        DEFAULT_LOCALE                       = "es"
        TRACE_ENABLED                        = "true"
        COST_TRACKING_ENABLED                = "true"
      }
    }

    # The customer app: public, holds no secret.
    "web-client" = {
      port        = 8080
      cpu         = "1"
      memory      = "512Mi"
      cpu_idle    = true
      min         = 0
      max         = 3
      concurrency = 80
      timeout     = "300s" # its BFF waits up to 150 s for a turn
      ingress     = "INGRESS_TRAFFIC_ALL"
      iap         = false
      subnet      = "edge"
      startup     = "/healthz"
      liveness    = "/healthz"
      env = {
        ORCHESTRATOR_URL = local.service_url["orchestrator"]
      }
    }

    # The agent back office: behind Identity-Aware Proxy, then its own login (ADR-0013).
    "web-backoffice" = {
      port        = 8080
      cpu         = "1"
      memory      = "512Mi"
      cpu_idle    = true
      min         = 0
      max         = 2
      concurrency = 80
      timeout     = "300s"
      ingress     = "INGRESS_TRAFFIC_ALL"
      iap         = true
      subnet      = "edge"
      startup     = "/healthz"
      liveness    = "/healthz"
      env = {
        APP_ENV             = "production"
        ORCHESTRATOR_URL    = local.service_url["orchestrator"]
        BANKING_CORE_URL    = local.service_url["banking-core"]
        DEMO_AGENT_EMAIL    = var.demo_agent_email
        UPSTREAM_TIMEOUT_MS = "30000" # absorbs an upstream cold start
      }
    }
  }

  enabled_services = var.services_enabled ? local.services : {}
}

resource "google_cloud_run_v2_service" "svc" {
  for_each = local.enabled_services

  name                = "${var.name_prefix}-${each.key}"
  location            = var.region
  ingress             = each.value.ingress
  deletion_protection = false
  # The backends and the customer app are not called with identity tokens: internal ingress
  # (or nothing, for the public app) is the control. The back office keeps the IAM check, and
  # only the IAP service agent may invoke it.
  invoker_iam_disabled = !each.value.iap
  iap_enabled          = each.value.iap

  labels = {
    app       = "pattern-blue"
    component = each.key
  }

  template {
    service_account                  = local.service_account_email[each.key]
    timeout                          = each.value.timeout
    max_instance_request_concurrency = each.value.concurrency

    scaling {
      min_instance_count = each.value.min
      max_instance_count = each.value.max
    }

    vpc_access {
      egress = "ALL_TRAFFIC"

      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.subnet[each.value.subnet].id
        tags       = [local.subnets[each.value.subnet].tag]
      }
    }

    containers {
      image = var.bootstrap_image

      ports {
        container_port = each.value.port
      }

      resources {
        limits = {
          cpu    = each.value.cpu
          memory = each.value.memory
        }
        # Must be explicit once resources is set, or the service bills as always-on.
        cpu_idle          = each.value.cpu_idle
        startup_cpu_boost = true
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

      # Up to 5 minutes to start: Direct VPC egress can take a minute to connect, and the model
      # server loads PyTorch.
      startup_probe {
        initial_delay_seconds = 0
        period_seconds        = 10
        timeout_seconds       = 5
        failure_threshold     = 30

        http_get {
          path = each.value.startup
        }
      }

      liveness_probe {
        period_seconds    = 30
        timeout_seconds   = 5
        failure_threshold = 3

        http_get {
          path = each.value.liveness
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.access,
    google_secret_manager_secret_version.value,
  ]
}

# Identity-Aware Proxy in front of the back office: the IAP service agent is its only invoker,
# and only the listed members pass IAP.
resource "google_project_service_identity" "iap" {
  provider = google-beta

  project = var.project_id
  service = "iap.googleapis.com"

  depends_on = [google_project_service.api]
}

resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  for_each = toset([for name, service in local.enabled_services : name if service.iap])

  name     = google_cloud_run_v2_service.svc[each.key].name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_project_service_identity.iap.email}"
}

resource "google_iap_web_cloud_run_service_iam_member" "access" {
  for_each = var.services_enabled ? toset(var.iap_members) : toset([])

  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.svc["web-backoffice"].name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.key
}

check "service_urls" {
  assert {
    condition = alltrue([
      for name, service in google_cloud_run_v2_service.svc : contains(service.urls, local.service_url[name])
    ])
    error_message = "A Cloud Run service does not list its deterministic URL, which the other services were given as their upstream; compare `terraform output service_urls` with the console."
  }
}

output "service_urls" {
  description = "The URL of each service. Only web-client and web-backoffice answer from the internet."
  value       = { for name in keys(local.enabled_services) : name => local.service_url[name] }
}
