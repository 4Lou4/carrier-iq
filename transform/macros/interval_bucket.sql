{#
  Truncate a timestamp to the start of its N-minute bucket, on whichever warehouse
  is running.

  ADR-001 named this as the one piece of DuckDB-specific SQL in the project and said
  the risk was managed rather than ignored. This macro is how it was managed:
  `time_bucket` exists in DuckDB and nowhere else, and Postgres reaches the same
  result with `date_bin`, which needs an explicit origin to count buckets from.

  The origin matters and is not decoration. date_bin measures whole intervals from a
  fixed point, so with an origin of 2000-01-01 00:00 UTC every 15-minute bucket falls
  on :00, :15, :30 and :45 — the same boundaries DuckDB's time_bucket uses. An origin
  on some arbitrary instant would shift every bucket by the same offset, silently, and
  the two warehouses would disagree about which interval an event belongs to.

  adapter.dispatch picks the implementation by warehouse. Adding a third warehouse
  means adding one macro here and changing nothing else.
#}
{% macro interval_bucket(column, minutes=15) %}
    {{ return(adapter.dispatch('interval_bucket', 'carrier_iq')(column, minutes)) }}
{% endmacro %}


{% macro duckdb__interval_bucket(column, minutes) %}
    time_bucket(interval '{{ minutes }} minutes', {{ column }})
{% endmacro %}


{% macro postgres__interval_bucket(column, minutes) %}
    date_bin(interval '{{ minutes }} minutes', {{ column }}, timestamp '2000-01-01 00:00:00')
{% endmacro %}


{% macro default__interval_bucket(column, minutes) %}
    {{ exceptions.raise_compiler_error(
        "interval_bucket has no implementation for adapter '" ~ target.type ~ "'. "
        ~ "Add a " ~ target.type ~ "__interval_bucket macro rather than letting the "
        ~ "model compile to something that looks right and buckets wrong."
    ) }}
{% endmacro %}
