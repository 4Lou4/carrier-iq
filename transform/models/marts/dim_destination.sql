-- One row per destination.
--
-- A destination is a country *and* a network type, not a country. The same country
-- costs a different amount on fixed and on mobile, so collapsing the two would
-- average two tariffs that never apply to the same call.

select
    md5(destination_code) as destination_key,
    destination_code,
    split_part(destination_code, '-', 2) as country_code,
    split_part(destination_code, '-', 3) as network_type,
    split_part(destination_code, '-', 3) = 'MOB' as is_mobile,
    count(*) as attempt_count

from {{ ref('stg_call_events') }}
group by destination_code
