# Veriscope on Google Cloud

Everything needed to run Veriscope in project `veriscope-515119`, as code.

```
browser ──▶ veriscope-web (Cloud Run, nginx, scale-to-zero)
                │  /api/*
                ▼
            veriscope-api (Cloud Run, FastAPI + local NLI/embeddings)
                │                       ▲ same image
                ▼                       │
   Cloud SQL Postgres 16 + pgvector ◀── veriscope-worker (Cloud Run, always-on)
   Memorystore Redis (queue/cache)      │
   GCS bucket (paper library)    ◀──────┘
   Vertex AI Gemini (service-account auth, no keys)
            veriscope-migrate (Cloud Run Job) runs before every deploy
```

Private by default: Cloud SQL and Redis have no public IP. Cloud Run reaches
them through Direct VPC egress. Secrets live in Secret Manager. CI deploys
through Workload Identity Federation, so there are no key files.

## What it costs at idle (estimates, asia-south1, check the pricing calculator)

| resource | default sizing | approx. / month |
|---|---|---|
| Cloud SQL | `db-g1-small`, 10 GB SSD, backups + PITR | ~$30-35 |
| Memorystore Redis | Basic, 1 GB | ~$40-50 |
| worker | 1 always-on instance, 2 vCPU / 4 GiB | ~$110-140 |
| api, web | scale to zero | ~$0 idle, pay per request |
| Artifact Registry, GCS, Secret Manager, logging | small | < $10 |
| **idle total** | | **~$190-235** |
| Vertex AI Gemini | per token, per run | depends on usage; `run_max_llm_calls` caps a run |

The cheap knobs, in order: `worker_min_instances` (the biggest line; the worker
must run for jobs to move, so 0 means runs wait until you scale it), `db_tier`,
and `api_min_instances` (keep 0 until there are users, then 1 to skip the
model-loading cold start). Set `billing_account` + `alert_email` so a budget
alert fires at 50 / 90 / 100%.

## Bootstrap (once)

Prerequisites: **billing linked to the project** (it is not yet), `gcloud` and
Terraform >= 1.6, Owner on the project.

```bash
gcloud auth application-default login
gcloud config set project veriscope-515119       # or pass --project everywhere

# 1. State bucket (holds generated secrets: private + versioned)
gcloud storage buckets create gs://veriscope-515119-tfstate --location=asia-south1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://veriscope-515119-tfstate --versioning
#    then uncomment the backend "gcs" block in main.tf

# 2. Apply
cd infra/gcp
cat > terraform.tfvars <<EOF
supabase_url    = "https://<ref>.supabase.co"
alert_email     = "you@example.com"
billing_account = "XXXXXX-XXXXXX-XXXXXX"
EOF
terraform init
terraform plan -out plan.tfplan     # read it: the first apply creates ~60 resources
terraform apply plan.tfplan
```

Cloud SQL and Memorystore take 10-15 minutes. The three Cloud Run services
start on a placeholder image; the first CI deploy replaces them.

## Connect CI

From `terraform output`, set these as repository **variables** (Settings ->
Secrets and variables -> Actions -> Variables):

| variable | value |
|---|---|
| `GCP_PROJECT_ID` | `veriscope-515119` |
| `GCP_REGION` | `asia-south1` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | output `workload_identity_provider` |
| `GCP_DEPLOYER_SA` | output `deployer_service_account` |

And these repository **secrets** for the web build (public by design, but kept
out of the workflow file): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`,
optionally `VITE_SENTRY_DSN`.

Add required reviewers to the `production` environment if every deploy should
wait for a human.

## After the first deploy

1. Open `terraform output web_url`; sign in; launch a small run.
2. In Supabase -> Authentication -> URL configuration, add the web URL as the
   Site URL and a redirect URL.
3. Optional secrets: `gcloud secrets versions add veriscope-smtp-password --data-file=-`
   (and set `SMTP_HOST`/`SMTP_USER` on the worker) for invite emails.
4. Confirm the Vertex model id (`vertex_model`) is available in Model Garden.

## Deliberately not here yet

- **Custom domain + HTTPS load balancer + Cloud Armor** (WAF, per-IP rate
  limits at the edge). Needs a domain. Until then the run.app URLs are the
  public surface and the app-level rate limiter is the only throttle.
- **Cross-region disaster recovery.** Backups + PITR are regional; a regional
  outage means restoring into another region by hand (~1h). Fine for launch,
  revisit with paying customers.
- **A staging environment.** Copy this directory with `name = "veriscope-stg"`
  and its own state prefix.
