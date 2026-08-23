{#
  One definition of what "unreadable" means, used in two places.

  The quarantine model needs it to decide what to hold back, and the staging model
  needs it to decide what to let through. Written twice, the two would drift, and a
  row would eventually be both quarantined and counted — or neither. Written once,
  they cannot disagree.

  Note what is NOT here: a missing purchase rate. That row is incomplete, not
  unreadable — it still describes a call that happened. It flows through and its
  coverage is watched by assert_buy_rate_coverage_above_threshold. Quarantining it
  would silently drop a fifth of the traffic and make the coverage gate look clean,
  which is the exact failure this project exists to prevent.
#}
{% macro quarantine_reason() %}
    case
        -- No identifier: the row cannot be deduplicated, so it cannot be counted once.
        when event_id is null then 'missing_event_id'
        -- A negative duration makes every aggregate over it meaningless.
        when billable_seconds < 0 then 'negative_billable_seconds'
        -- An instant that has not happened yet would land in a bucket still open.
        when occurred_at > current_timestamp then 'occurred_in_the_future'
    end
{% endmacro %}
