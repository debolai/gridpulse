{#
  Incremental correctness (blueprint: monthly dbt_full_refresh_check). After the marts are
  rebuilt from scratch under GRIDPULSE_SCHEMA_PREFIX=<prefix>, compare every mart table with
  production, both ways (not the semantic time spines: they depend on today's date):
    dbt run-operation compare_full_refresh --args '{prefix: frc_20261101}'
  Doubles are compared rounded to 6 decimals (summation order leaves ~1e-9 noise). Rows from the
  last `settle_days` (by period_utc, or started_at_utc for ingestion runs) are left out, by
  default the revision window + 2 days: ingestion may still change those hours between the
  rebuild and the comparison (seen when the daily sweep landed mid-check: 26 days differed).
  Older rows are final, and every one of them was built incrementally. Fails on any difference.
#}
{% macro compare_full_refresh(prefix, settle_days=none) %}
    {% set settle_days = settle_days if settle_days is not none
        else var('revision_window_days') + 2 %}
    {% if not prefix or prefix | length < 3 %}
        {{ exceptions.raise_compiler_error("compare_full_refresh needs the scratch prefix") }}
    {% endif %}
    {% set cutoff = (modules.datetime.datetime.utcnow()
        - modules.datetime.timedelta(days=settle_days)).strftime('%Y-%m-%d 00:00:00') %}
    {% set failures = [] %}
    {% set models = graph.nodes.values() | selectattr('resource_type', 'equalto', 'model') %}
    {% for node in models | sort(attribute='name')
          if 'marts' in node.fqn and 'semantic' not in node.fqn
          and node.config.materialized in ('table', 'incremental') %}
        {% set prod = api.Relation.create(
            database=target.database, schema=node.schema, identifier=node.alias) %}
        {% set scratch = api.Relation.create(
            database=target.database, schema=prefix ~ '_' ~ node.schema, identifier=node.alias) %}
        {% set columns = adapter.get_columns_in_relation(prod) %}
        {% set names = columns | map(attribute='name') | map('lower') | list %}
        {% set select_list = [] %}
        {% for col in columns %}
            {% if col.data_type | lower in ('double', 'real', 'float') %}
                {% do select_list.append('round(' ~ col.name ~ ', 6) as ' ~ col.name) %}
            {% else %}
                {% do select_list.append(col.name) %}
            {% endif %}
        {% endfor %}
        {% set time_col = 'period_utc' if 'period_utc' in names
            else ('started_at_utc' if 'started_at_utc' in names else none) %}
        {% set where = "where " ~ time_col ~ " < timestamp '" ~ cutoff ~ "'" if time_col else '' %}
        {% set side = 'select ' ~ select_list | join(', ') ~ ' from {rel} ' ~ where %}
        {% set sql %}
            select
                (select count(*) from ({{ side | replace('{rel}', prod | string) }}
                    except {{ side | replace('{rel}', scratch | string) }}) as d) as only_in_prod,
                (select count(*) from ({{ side | replace('{rel}', scratch | string) }}
                    except {{ side | replace('{rel}', prod | string) }}) as d) as only_in_rebuild,
                (select count(*) from ({{ side | replace('{rel}', prod | string) }}) as p) as prod_rows
        {% endset %}
        {% set row = run_query(sql).rows[0] %}
        {% set ok = row[0] == 0 and row[1] == 0 %}
        {% do log(('OK   ' if ok else 'DIFF ') ~ node.name ~ ': ' ~ row[2] ~ ' rows compared, '
            ~ row[0] ~ ' only in production, ' ~ row[1] ~ ' only in the full rebuild', info=true) %}
        {% if not ok %}{% do failures.append(node.name) %}{% endif %}
    {% endfor %}
    {% if failures %}
        {{ exceptions.raise_compiler_error(
            "incremental output differs from a full rebuild: " ~ failures | join(', ')) }}
    {% endif %}
    {% do log('incremental output equals a full rebuild (rows before ' ~ cutoff ~ ')', info=true) %}
{% endmacro %}
