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


{#
  The zone-less timestamp type for UTC instants. Trino's Iceberg type is timestamp(6); Athena
  views live in the Glue/Hive catalog, whose only timestamp type is plain `timestamp`.
  Mart contracts can't call macros (YAML is rendered without them), so they repeat this
  choice inline: data_type: "{{ 'timestamp' if target.type == 'athena' else 'timestamp(6)' }}".
#}
{% macro timestamp_type() -%}
    {{ return(adapter.dispatch('timestamp_type', 'gridpulse')()) }}
{%- endmacro %}

{% macro default__timestamp_type() -%}timestamp(6){%- endmacro %}

{% macro athena__timestamp_type() -%}timestamp{%- endmacro %}


{# A source timestamp (UTC instant, with or without zone) as a zone-less UTC timestamp. #}
{% macro to_utc_timestamp(column) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'gridpulse')(column)) }}
{%- endmacro %}

{% macro default__to_utc_timestamp(column) -%}
    cast({{ column }} at time zone 'UTC' as {{ timestamp_type() }})
{%- endmacro %}


{# A zone-less UTC timestamp as wall-clock time in an IANA zone (column or literal). DST-aware. #}
{% macro utc_to_local(column, time_zone) -%}
    {{ return(adapter.dispatch('utc_to_local', 'gridpulse')(column, time_zone)) }}
{%- endmacro %}

{% macro default__utc_to_local(column, time_zone) -%}
    cast(at_timezone(with_timezone({{ column }}, 'UTC'), {{ time_zone }}) as {{ timestamp_type() }})
{%- endmacro %}

{#
  Athena casts a zoned timestamp to `timestamp` by converting to UTC (Trino keeps the wall
  clock), which silently turns every local time back into UTC. Format the zoned value as text
  in its own zone, then parse it. Caught by the DST unit test on 2026-10-12.
#}
{% macro athena__utc_to_local(column, time_zone) -%}
    date_parse(
        format_datetime(at_timezone(with_timezone({{ column }}, 'UTC'), {{ time_zone }}), 'yyyy-MM-dd HH:mm:ss'),
        '%Y-%m-%d %H:%i:%s'
    )
{%- endmacro %}


{# Highest value of a column already loaded into this incremental model (epoch if empty). #}
{% macro incremental_watermark(column) -%}
    (select coalesce(max({{ column }}), timestamp '1970-01-01 00:00:00') from {{ this }})
{%- endmacro %}
