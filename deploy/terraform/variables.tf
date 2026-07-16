variable "project_id" {
  type        = string
  description = "GCP project id"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Pin to the region nearest the configured STT/LLM/TTS endpoints"
}

variable "db_tier" {
  type    = string
  default = "db-custom-4-16384"
}

variable "agent_warm_nodes" {
  type        = number
  default     = 2
  description = "Warm agent-pool nodes so a call never waits on a cold start"
}

variable "recording_retention_days_max" {
  type        = number
  default     = 730
  description = "Hard ceiling; per-firm retention (firms.retention_days) is enforced below it"
}
