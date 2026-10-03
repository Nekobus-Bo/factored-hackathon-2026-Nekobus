# infra/deploy/gcp

Terraform for the presentation environment on Google Cloud Run ([ADR-0015](../../../docs/adr/0015-gcp-cloud-run-terraform.md)). How it deploys and what it keeps from the compose trust boundary: [docs/deployment.md](../../../docs/deployment.md), sections 6 and 7.

⚠️ **Not yet exercised.** Everything here is checked offline (`make gcp-check`); no apply has run against a real project. Until the first run is logged in docs/deployment.md, treat the steps below as the intended procedure, not a proven one.

## What is where

| File | What it creates |
|---|---|
| `apis.tf` | The APIs the environment uses |
| `network.tf` | The VPC; subnets `core` (banking-core and its jobs), `edge` (model server, front ends) and `egress` (the orchestrator, the only one with Cloud NAT); private service access; the firewall rules that keep edge away from core data |
| `data.tf` | Cloud SQL for PostgreSQL 17 (private IP only) and one Memorystore Redis per trust zone |
| `secrets.tf` | Secret Manager: seven generated secrets, the three connection URLs, and an empty `llm-api-key` |
| `iam.tf` | One service account per service and job, and exactly the secrets each reads (the trust boundary) |
| `registry.tf` | The Artifact Registry repository `deploy.yml` pushes to |
| `services.tf` | The five Cloud Run services, Identity-Aware Proxy on the back office |
| `jobs.tf`, `netcheck.py` | The migrate, seed and netcheck jobs |
| `ci.tf` | Workload Identity Federation for `deploy.yml` and the deployer service account |
| `tests/` | `terraform test` against a mocked provider: trust boundary, ingress, network, sizing, CI identity, pins, decision model |
| `smoke.sh` | The check of a deployed environment from outside (`make gcp-smoke`) |

Inputs: `presentation.tfvars` (versioned, non-secret) and `local.tfvars` (yours, not versioned; copy `local.tfvars.example`). Terraform owns the infrastructure and the service configuration; `deploy.yml` owns which image each service and job runs.

## Before you start

- A GCP project with billing, preferably outside any employer organization, where you are Owner. With no organization, IAP needs an OAuth client created by hand (step 5).
- `gcloud` (logged in: `gcloud auth login` and `gcloud auth application-default login`), Terraform 1.11 or later, `gh`.
- A GitHub repository you administer, holding this code: `deploy.yml` logs in only from it.
- An LLM API key, ideally in its own provider project with a spend limit.
- A budget alert on the billing account. With `warm = true` expect about $8–11 a day; with `warm = false` about $3.5–4.

## First deploy

```bash
cp infra/deploy/gcp/local.tfvars.example infra/deploy/gcp/local.tfvars   # project, repository, IAP members

make gcp-state                 # 1. the Terraform state bucket (once per project)
make gcp-init                  # 2. terraform init against it
make gcp-apply SERVICES=false  # 3. everything but the Cloud Run services and jobs
make gcp-llm-key               # 4. the LLM key, from a hidden prompt; it never enters the state
make gcp-iap-oauth             # 5. no organization only: the OAuth client for IAP (below), ID and hidden secret
make gcp-apply                 # 6. the services and jobs, on Google's placeholder image
make gcp-gh-vars GH_REPO=owner/name DEMO_SEED=true   # 7. deploy.yml's repository variables
```

Step 5 exists because a project with no organization cannot create IAP's OAuth client through the API ([Cloud Run IAP docs](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)). In the console, under Google Auth Platform: **Branding**, create the brand with audience **External**; **Audience**, add every `iap_members` account as a test user while the app is in testing; **Clients**, create a **Web application** client with the authorized redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/CLIENT_ID:handleRedirect` (its own ID in place of `CLIENT_ID`). `make gcp-iap-oauth` then sets it as the project's IAP OAuth client; the secret goes through a hidden prompt and a temporary file readable only by you, deleted afterwards. Terraform does the rest (IAP on the back office, its invoker, `iap_members`).

8. Push to `main` of that repository (or `make deploy GH_REPO=owner/name`): `ci`, then `deploy`, build the images, run the migrations, seed the demo customers, roll every service out and run the smoke test.
9. `make gcp-smoke NETCHECK=1`, then in a browser: the web client URL (`terraform -chdir=infra/deploy/gcp output service_urls`) for a lost-card conversation, and the back office through IAP with `agent@demo.local` and the password from `gcloud secrets versions access latest --secret pb-demo-agent-password`.

## Day to day

| Command | What it does |
|---|---|
| `make deploy` | Build and roll out the latest `main` |
| `make gcp-plan`, `make gcp-apply` | Change the infrastructure or a service's configuration |
| `make gcp-seed` | Reload the synthetic demo customers (truncates the banking tables) |
| `make gcp-migrate`, `make gcp-netcheck` | Run those jobs by hand |
| `make gcp-smoke` | Check the environment from outside |
| `make gcp-backoffice-open JUDGES=N`, `make gcp-judges`, `make gcp-backoffice-close` | Open the back office to judges for a window (no IAP, one login each), print their logins, close it again ([deployment.md](../../../docs/deployment.md), section 7) |
| `make gcp-check` | The offline gate CI runs |

Set `warm = false` in `local.tfvars` and `make gcp-apply` between presentations: every service scales to zero, and Cloud SQL and the two Redis instances are what remains billed.

## Teardown

`gcloud projects delete PROJECT` is the reliable way. `make gcp-destroy` needs `data_deletion_protection = false` first, and after Cloud SQL is deleted the network peering stays busy for days, so Terraform abandons it instead of deleting it.
