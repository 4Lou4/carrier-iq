-- Airflow keeps its own metadata (runs, task states, retries) in a database.
-- It shares the same server as the warehouse but never the same database: mixing
-- orchestrator bookkeeping with the data being orchestrated makes both harder to
-- reason about, and makes "drop the warehouse and reload" destroy the run history.
--
-- Runs only when the Postgres volume is created for the first time. On an existing
-- volume, create it by hand:
--   docker compose exec warehouse psql -U carrier_iq -c "create database airflow"
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
