output "gke_cluster" {
  value = google_container_cluster.caseline.name
}

output "sql_connection_name" {
  value = google_sql_database_instance.postgres.connection_name
}

output "redis_host" {
  value = google_redis_instance.sessions.host
}

output "pubsub_topic" {
  value = google_pubsub_topic.events.id
}

output "recordings_bucket" {
  value = google_storage_bucket.recordings.name
}

output "kms_key" {
  value = google_kms_crypto_key.cms_credentials.id
}
