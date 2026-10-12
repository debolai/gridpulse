{#
  Engine differences between Trino (local) and Athena v3 (AWS) live here and nowhere else.
  Each macro dispatches on the adapter: trino__ / athena__ implementations, default__ fallback.
#}

{# Table settings for an Iceberg table partitioned by the given transforms. #}
{% macro iceberg_table_config(partition_by=[]) -%}
    {{ return(adapter.dispatch('iceberg_table_config', 'gridpulse')(partition_by)) }}
{%- endmacro %}

{% macro trino__iceberg_table_config(partition_by) -%}
    {%- set props = {'format': "'PARQUET'"} -%}
    {%- if partition_by -%}
        {%- do props.update({'partitioning': "ARRAY[" ~ ("'" ~ partition_by | join("', '") ~ "'") ~ "]"}) -%}
    {%- endif -%}
    {{ return({'properties': props}) }}
{%- endmacro %}

{% macro athena__iceberg_table_config(partition_by) -%}
    {{ return({'table_type': 'iceberg', 'format': 'parquet', 'partitioned_by': partition_by}) }}
{%- endmacro %}


{# A source timestamp (UTC instant, with or without zone) as a zone-less UTC timestamp(6). #}
{% macro to_utc_timestamp(column) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'gridpulse')(column)) }}
{%- endmacro %}

{% macro default__to_utc_timestamp(column) -%}
    cast({{ column }} at time zone 'UTC' as timestamp(6))
{%- endmacro %}


{# A zone-less UTC timestamp as wall-clock time in an IANA zone (column or literal). DST-aware. #}
{% macro utc_to_local(column, time_zone) -%}
    {{ return(adapter.dispatch('utc_to_local', 'gridpulse')(column, time_zone)) }}
{%- endmacro %}

{% macro default__utc_to_local(column, time_zone) -%}
    cast(at_timezone(with_timezone({{ column }}, 'UTC'), {{ time_zone }}) as timestamp(6))
{%- endmacro %}


{# Highest value of a column already loaded into this incremental model (epoch if empty). #}
{% macro incremental_watermark(column) -%}
    (select coalesce(max({{ column }}), timestamp '1970-01-01 00:00:00') from {{ this }})
{%- endmacro %}
