output "bucket_names" {
  description = "Bucket name per role: raw, lake, athena_results."
  value       = { for k, b in aws_s3_bucket.this : k => b.id }
}

output "bucket_arns" {
  description = "Bucket ARN per role."
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}
