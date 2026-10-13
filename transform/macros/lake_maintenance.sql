{#
  Weekly Iceberg maintenance (blueprint: compaction and snapshot expiry), run by the
  lake_maintenance DAG:
    dbt run-operation lake_maintenance                      # every raw source and dbt table
    dbt run-operation lake_maintenance --args '{dry_run: true}'
  Frequent MERGEs from revisions leave small files and many snapshots: compaction keeps queries
  fast, expiry bounds storage, and 30 days of snapshots stay for time travel. Views, seeds and
  ephemeral models are skipped (seeds are rewritten whole on every load).
#}
{% macro lake_maintenance(dry_run=false, retention_days=30) %}
    {% set tables = [] %}
    {% for source in graph.sources.values() %}
        {% do tables.append(source.schema ~ '.' ~ source.identifier) %}
    {% endfor %}
    {% for node in graph.nodes.values() %}
        {% if node.resource_type == 'snapshot'
              or (node.resource_type == 'model'
                  and node.config.materialized in ('table', 'incremental')) %}
            {% do tables.append(node.schema ~ '.' ~ node.alias) %}
        {% endif %}
    {% endfor %}
    {% for table in tables | unique | sort %}
        {% for statement in gridpulse.iceberg_maintenance_statements(table, retention_days) %}
            {% do log(('[dry run] ' if dry_run else '') ~ statement, info=true) %}
            {% if not dry_run %}{% do run_query(statement) %}{% endif %}
        {% endfor %}
    {% endfor %}
    {% do log('maintained ' ~ (tables | unique | list | length) ~ ' Iceberg table(s)', info=true) %}
{% endmacro %}

{% macro iceberg_maintenance_statements(table, retention_days) -%}
    {{ return(adapter.dispatch('iceberg_maintenance_statements', 'gridpulse')(table, retention_days)) }}
{%- endmacro %}

{% macro trino__iceberg_maintenance_statements(table, retention_days) -%}
    {%- set relation = target.database ~ '.' ~ table -%}
    {{ return([
        'alter table ' ~ relation ~ ' execute optimize',
        'alter table ' ~ relation ~ " execute expire_snapshots(retention_threshold => '"
            ~ retention_days ~ "d')",
        'alter table ' ~ relation ~ " execute remove_orphan_files(retention_threshold => '"
            ~ retention_days ~ "d')",
    ]) }}
{%- endmacro %}

{# Athena's VACUUM expires snapshots older than the table's vacuum_max_snapshot_age_seconds
   (default 5 days) and removes orphan files, so the retention is set on the table first. #}
{% macro athena__iceberg_maintenance_statements(table, retention_days) -%}
    {{ return([
        'optimize ' ~ table ~ ' rewrite data using bin_pack',
        'alter table ' ~ table ~ " set tblproperties ('vacuum_max_snapshot_age_seconds'='"
            ~ (retention_days * 86400) ~ "')",
        'vacuum ' ~ table,
    ]) }}
{%- endmacro %}
