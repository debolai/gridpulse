{#
  Drop every schema built under a GRIDPULSE_SCHEMA_PREFIX (tests, CI, full-refresh checks).
    dbt run-operation drop_prefixed_schemas --args '{prefix: ci_pr_42}'
  Refuses an empty prefix so it can never touch the real layer schemas.
#}
{% macro drop_prefixed_schemas(prefix) %}
    {% if not prefix or prefix | length < 3 %}
        {{ exceptions.raise_compiler_error("drop_prefixed_schemas needs a prefix of 3+ characters") }}
    {% endif %}
    {% set schemas = run_query(
        "select schema_name from information_schema.schemata where schema_name like '"
        ~ prefix ~ "\\_%' escape '\\'"
    ) %}
    {% for row in schemas.rows %}
        {% do log("dropping schema " ~ row[0], info=true) %}
        {% do run_query(gridpulse.drop_schema_cascade(row[0])) %}
    {% endfor %}
    {% do log("dropped " ~ schemas.rows | length ~ " schema(s) with prefix " ~ prefix, info=true) %}
{% endmacro %}

{% macro drop_schema_cascade(schema) -%}
    {{ return(adapter.dispatch('drop_schema_cascade', 'gridpulse')(schema)) }}
{%- endmacro %}

{% macro default__drop_schema_cascade(schema) -%}
    drop schema if exists {{ target.database }}.{{ schema }} cascade
{%- endmacro %}

{% macro athena__drop_schema_cascade(schema) -%}
    drop database if exists `{{ schema }}` cascade
{%- endmacro %}
