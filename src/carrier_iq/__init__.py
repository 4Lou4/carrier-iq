"""carrier-iq — an end-to-end data platform on synthetic telecom routing events.

The pipeline is deliberately built in the order a real one has to be built:

    generator  →  dlt (extract + load)  →  DuckDB (raw)  →  dbt (transform + test)

Nothing in this repository is real. Carriers, destinations, tariffs and traffic are
all produced by the seeded generator in :mod:`carrier_iq.generator`.
"""

__version__ = "0.1.0"
