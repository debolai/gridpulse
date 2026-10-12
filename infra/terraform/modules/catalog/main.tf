# Glue databases (one per lake layer) and Athena workgroups with per-query scan limits,
# so a bad or LLM-generated query cannot run up a bill.

locals {
  # Raw Iceberg tables live in the raw bucket; dbt-built layers in the lake bucket.
  databases = {
    raw          = "s3://${var.raw_bucket}/iceberg/raw/"
    staging      = "s3://${var.lake_bucket}/staging/"
    intermediate = "s3://${var.lake_bucket}/intermediate/"
    marts        = "s3://${var.lake_bucket}/marts/"
    reference    = "s3://${var.lake_bucket}/reference/"
  }

  workgroups = {
    "gridpulse-${var.env}"       = var.query_scan_limit_bytes
    "gridpulse-${var.env}-agent" = var.agent_scan_limit_bytes
  }
}

resource "aws_glue_catalog_database" "this" {
  for_each     = local.databases
  name         = each.key
  location_uri = each.value
  description  = "GridPulse ${each.key} layer (${var.env})"
}

resource "aws_athena_workgroup" "this" {
  for_each      = local.workgroups
  name          = each.key
  force_destroy = true # only drops saved queries and history, never data

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = each.value

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${var.athena_results_bucket}/${each.key}/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
