# Caseline production infrastructure (Phase 2 Workstream A).
#
# Everything the architecture doc names, as code: GKE (agent workers + API +
# self-hosted LiveKit SFU), Cloud SQL Postgres, Memorystore Redis, Pub/Sub,
# GCS (recordings with per-firm-configurable retention), KMS for credential
# encryption, Artifact Registry for images.
#
# STATUS: written and reviewed, NOT applied — no GCP project/billing account
# is provisioned yet (the same account blocker as the provider keys). Apply
# order once one exists:
#   terraform init && terraform plan -var-file=prod.tfvars && terraform apply
#
# Regional pinning (guiding principle: the hot path is sacred): everything
# lands in var.region, chosen to be the region nearest the STT/LLM/TTS
# provider endpoints actually configured — re-derive when providers change.

terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
  # State bucket is created out-of-band once per org.
  backend "gcs" {
    bucket = "caseline-tfstate"
    prefix = "prod"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- GKE: one autoscaling pool for API/workers, one for voice agents -------

resource "google_container_cluster" "caseline" {
  name     = "caseline-${var.env}"
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = var.env == "prod"

  release_channel {
    channel = "REGULAR"
  }
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "services" {
  name     = "services"
  cluster  = google_container_cluster.caseline.id
  location = var.region

  autoscaling {
    min_node_count = 1
    max_node_count = 10
  }
  node_config {
    machine_type = "e2-standard-4"
    labels       = { pool = "services" }
  }
}

# Voice agents: one worker per active call, warm pool so cold starts never
# eat first-turn latency (min_node_count keeps capacity resident; the Helm
# HPA keeps warm agent replicas on top of it).
resource "google_container_node_pool" "agents" {
  name     = "agents"
  cluster  = google_container_cluster.caseline.id
  location = var.region

  autoscaling {
    min_node_count = var.agent_warm_nodes
    max_node_count = 50
  }
  node_config {
    machine_type = "c2-standard-8" # compute-optimized: audio + VAD are CPU-bound
    labels       = { pool = "agents" }
    taint {
      key    = "caseline.dev/agents"
      value  = "true"
      effect = "NO_SCHEDULE"
    }
  }
}

# --- Cloud SQL Postgres ------------------------------------------------------

resource "google_sql_database_instance" "postgres" {
  name             = "caseline-${var.env}"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier
    availability_type = var.env == "prod" ? "REGIONAL" : "ZONAL"
    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.id
    }
    database_flags {
      name  = "max_connections"
      value = "400" # sized for CASELINE_DB_POOL_SIZE x replica count, with margin
    }
  }
}

resource "google_sql_database" "caseline" {
  name     = "caseline"
  instance = google_sql_database_instance.postgres.name
}

# --- Memorystore Redis (session state / config cache) ------------------------

resource "google_redis_instance" "sessions" {
  name           = "caseline-sessions-${var.env}"
  tier           = var.env == "prod" ? "STANDARD_HA" : "BASIC"
  memory_size_gb = 1
  region         = var.region
}

# --- Pub/Sub (event fan-out beyond the outbox) --------------------------------

resource "google_pubsub_topic" "events" {
  name = "caseline-events-${var.env}"
}

resource "google_pubsub_subscription" "cms_sync" {
  name  = "caseline-cms-sync-${var.env}"
  topic = google_pubsub_topic.events.id

  ack_deadline_seconds = 60
  retry_policy {
    minimum_backoff = "30s"
    maximum_backoff = "600s"
  }
  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.events_dlq.id
    max_delivery_attempts = 5 # mirrors events.MAX_ATTEMPTS
  }
}

resource "google_pubsub_topic" "events_dlq" {
  name = "caseline-events-dlq-${var.env}"
}

# --- GCS: recordings + raw transcripts, lifecycle-managed ---------------------

resource "google_storage_bucket" "recordings" {
  name                        = "${var.project_id}-caseline-recordings-${var.env}"
  location                    = var.region
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = var.recording_retention_days_max
    }
    action {
      type = "Delete"
    }
  }
  # Per-firm retention below this ceiling is enforced by the retention job
  # reading firms.retention_days.
}

# --- KMS: credential encryption (SecretsCipher -> KmsCipher) ------------------

resource "google_kms_key_ring" "caseline" {
  name     = "caseline-${var.env}"
  location = var.region
}

resource "google_kms_crypto_key" "cms_credentials" {
  name            = "cms-credentials"
  key_ring        = google_kms_key_ring.caseline.id
  rotation_period = "7776000s" # 90 days
}

# --- Artifact Registry + network ----------------------------------------------

resource "google_artifact_registry_repository" "images" {
  repository_id = "caseline"
  format        = "DOCKER"
  location      = var.region
}

resource "google_compute_network" "vpc" {
  name                    = "caseline-${var.env}"
  auto_create_subnetworks = true
}
