output "database_names" {
  description = "Glue database names."
  value       = keys(aws_glue_catalog_database.this)
}

output "workgroup_names" {
  description = "Athena workgroup names."
  value       = keys(aws_athena_workgroup.this)
}
