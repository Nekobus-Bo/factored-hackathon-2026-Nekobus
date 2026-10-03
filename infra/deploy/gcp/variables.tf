# Inputs. Non-secret defaults for the presentation environment are in presentation.tfvars;
# what identifies you (project, repository, IAP accounts) goes in local.tfvars, which is not
# versioned (local.tfvars.example lists it).

variable "project_id" {
  description = "GCP project, created by hand with billing (ADR-0015)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a GCP project id: 6 to 30 lowercase letters, digits or hyphens."
  }
}

variable "region" {
  description = "Region for every regional resource."
  type        = string
  default     = "us-east1"
}

variable "name_prefix" {
  description = "Prefix of every resource name, so several environments can share a project."
  type        = string
  default     = "pb"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{0,5}$", var.name_prefix))
    error_message = "name_prefix must be 1 to 6 lowercase letters or digits, starting with a letter (service account ids are limited to 30 characters)."
  }
}

variable "sql_tier" {
  description = "Cloud SQL machine tier. db-g1-small allows 50 connections; each banking-core instance opens up to 15."
  type        = string
  default     = "db-g1-small"
}

variable "data_deletion_protection" {
  description = "Protect the Cloud SQL instance from `terraform destroy`. Set false only to tear the environment down."
  type        = bool
  default     = true
}

variable "services_enabled" {
  description = "Create the Cloud Run services and jobs. The first apply sets it false: a revision whose secret has no version fails, so the LLM key is added before the services exist."
  type        = bool
  default     = true
}

variable "warm" {
  description = "Keep one instance of the encoder, banking-core and the orchestrator running (no cold starts during a presentation). False scales everything to zero between presentations."
  type        = bool
  default     = true
}

variable "bootstrap_image" {
  description = "Image a service or job starts with before deploy.yml rolls out the real one. Terraform ignores image changes afterwards."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "iap_members" {
  description = "Who passes Identity-Aware Proxy to the back office, as IAM members (user:someone@example.com, group:...)."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for member in var.iap_members : can(regex("^(user|group|domain):[^ ]+$", member))])
    error_message = "Each IAP member must be user:EMAIL, group:EMAIL or domain:DOMAIN."
  }
}

variable "demo_agent_email" {
  description = "The back office's one demo login, recorded on every claim and takeover."
  type        = string
  default     = "agent@demo.local"

  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+$", var.demo_agent_email))
    error_message = "demo_agent_email must look like an e-mail address."
  }
}

# The judging window (ADR-0015, amendment of 2026-10-03). Both off by default: an apply that
# does not set them puts IAP back and drops the judge logins. `make gcp-backoffice-open` sets them.
variable "backoffice_public" {
  description = "Open the back office to anyone for an evaluation window: no Identity-Aware Proxy, so its own login is its only lock."
  type        = bool
  default     = false
}

variable "judge_accounts" {
  description = "How many judge logins to generate (judge1 to judgeN at the demo agent's domain, random passwords in Secret Manager). 0 is none."
  type        = number
  default     = 0

  validation {
    condition     = var.judge_accounts >= 0 && var.judge_accounts <= 20 && floor(var.judge_accounts) == var.judge_accounts
    error_message = "judge_accounts must be a whole number from 0 to 20."
  }
}

variable "llm_model" {
  description = "LiteLLM model id of the conversational model (ADR-0001). The openai/ prefix pins the provider."
  type        = string
  default     = "openai/gpt-6-luna"
}

variable "llm_reasoning_effort" {
  description = "Sent as reasoning_effort; GPT 6 Luna accepts temperature 0 only with \"none\". Empty sends nothing."
  type        = string
  default     = "none"
}

variable "trusted_proxy_hops" {
  description = "Reverse proxies in front of the orchestrator. 0 on Cloud Run until the web-client BFF forwards the client address (ADR-0015 stopgap)."
  type        = number
  default     = 0

  validation {
    condition     = var.trusted_proxy_hops >= 0 && var.trusted_proxy_hops <= 8
    error_message = "trusted_proxy_hops must be between 0 and 8."
  }
}

variable "rate_limit_conversations_per_ip_hour" {
  description = "Conversations one client address may open per hour. High on Cloud Run: every customer shares one address until the stopgap is removed (ADR-0015)."
  type        = number
  default     = 1000

  validation {
    condition     = var.rate_limit_conversations_per_ip_hour >= 1
    error_message = "rate_limit_conversations_per_ip_hour must be at least 1 (0 is not unlimited: the orchestrator refuses it)."
  }
}

variable "embedding_model" {
  description = "The kb.search embedding model, baked into the encoder image and checked by banking-core. Must match .env.example."
  type        = string
  default     = "ibm-granite/granite-embedding-311m-multilingual-r2"
}

variable "embedding_revision" {
  description = "The pinned commit of embedding_model. Must match .env.example."
  type        = string
  default     = "44399559930365213510b1ee2eb15ded83374f0e"

  validation {
    condition     = can(regex("^[0-9a-f]{40}$", var.embedding_revision))
    error_message = "embedding_revision must be a full 40-hex commit (a branch is not a pin)."
  }
}

variable "embedding_weights_sha256" {
  description = "SHA-256 of the pinned weights file. Must match .env.example."
  type        = string
  default     = "dcb6431bfa6e817fe100a2b0521360cec3383963b03fa966b685de18ca310d31"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.embedding_weights_sha256))
    error_message = "embedding_weights_sha256 must be 64 lowercase hex characters."
  }
}

variable "decision_points_file" {
  description = "Calibration artifact the encoder serves, relative to the image's /app. The pooled DistilBERT (ADR-0014), as in .env.example; packages/encoder/calibration/decision_points.json is the tfidf_lr kill switch, already in the image."
  type        = string
  default     = "packages/encoder/calibration/decision_points.distilbert.json"

  validation {
    condition     = can(regex("^packages/encoder/calibration/[a-z0-9_.]+\\.json$", var.decision_points_file))
    error_message = "decision_points_file must be a .json artifact under packages/encoder/calibration/."
  }
}

variable "decision_points_modes" {
  description = "DECISION_POINTS_MODES for the orchestrator: id=mode pairs that override decision_effects.yaml, e.g. \"intent_hint=shadow,clarify_route=shadow\" (the kill switch of ADR-0014, amendment 2026-10-01). Empty keeps the shipped modes."
  type        = string
  default     = ""

  validation {
    condition     = can(regex("^([a-z][a-z0-9_]{2,40}=(off|shadow|enforce)(,[a-z][a-z0-9_]{2,40}=(off|shadow|enforce))*)?$", var.decision_points_modes))
    error_message = "decision_points_modes must be empty or id=mode pairs separated by commas, mode one of off, shadow, enforce."
  }
}

variable "github_repository" {
  description = "The repository whose deploy.yml may deploy, as owner/name, exactly as GitHub spells it."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must be owner/name."
  }
}

variable "github_repository_id" {
  description = "The numeric id of github_repository (gh api repos/OWNER/NAME --jq .id). The login is bound to it, which survives a rename."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be the numeric repository id."
  }
}
