# Airflow, plus this project.
#
# The scheduler has to be able to import carrier_iq and run dbt, so the image is the
# official one with the project installed on top. Pinned rather than :latest: an
# orchestrator that changes version on its own is the opposite of an orchestrator.
FROM apache/airflow:3.0.2-python3.11

USER root
# dbt-postgres builds against libpq. Installing the client library here keeps the
# wheel install below from needing a compiler.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    && rm -rf /var/lib/apt/lists/*

USER airflow
COPY --chown=airflow:root pyproject.toml README.md /opt/carrier-iq/
COPY --chown=airflow:root src /opt/carrier-iq/src
RUN pip install --no-cache-dir "/opt/carrier-iq[dbt,postgres]"
