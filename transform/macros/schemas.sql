{#
  Schemas are named by layer (staging, intermediate, marts, reference) with no target prefix,
  so local and AWS look the same. GRIDPULSE_SCHEMA_PREFIX isolates throwaway builds:
  tests use test_<id>, CI uses ci_pr_<n>, and both drop their schemas afterwards.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set base = custom_schema_name if custom_schema_name is not none else target.schema -%}
    {%- set prefix = env_var('GRIDPULSE_SCHEMA_PREFIX', '') -%}
    {%- if prefix -%}{{ prefix }}_{{ base | trim }}{%- else -%}{{ base | trim }}{%- endif -%}
{%- endmacro %}
