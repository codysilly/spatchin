# C070 airport registry input

`docs/reference/c070-airports.csv` is the owner-supplied C070 Sheet1 column A
export.  It is intentionally only an allow-list, not an airport registry.

Before a C070 NOTAM snapshot can be built, provide a reviewed JSON registry to
`scripts/c070_notam_partition.py`.  Each entry must contain the exact C070 IATA
code, a verified ICAO identifier, airport name, and source-coverage metadata.
The importer rejects incomplete registries and does not derive ICAO values by
prefixing IATA codes.  This is important for identifiers whose mappings change
or do not follow a simple convention.

The private DOMESTIC response is not an input to this repository and must never
be copied here.  The partitioner only reads an operator-supplied local file and
writes its result to stdout; publication is a separate reviewed action.
