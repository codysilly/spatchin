# C070 airport registry

`docs/reference/c070-airport-registry.json` is the reviewed registry consumed by
the offline partitioner. It contains exactly the 130 codes from the owner-supplied
`docs/reference/c070-airports.csv` C070 Sheet1 column-A export.

The primary record source is FAA NASR `APT_BASE.csv`, effective **2026-10-29**,
from [the FAA NASR subscription](https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-10-29/)
and its [APT CSV archive](https://nfdc.faa.gov/webContent/28DaySub/extra/29_Oct_2026_APT_CSV.zip).
The builder reads named `ARPT_ID`, `ICAO_ID`, and `ARPT_NAME` columns, rather
than field positions. The secondary cross-reference is the OurAirports
[`airports.csv`](https://davidmegginson.github.io/ourairports-data/airports.csv),
retrieved 2026-11-16; its named `iata_code`, `icao_code`, `gps_code`, and `name`
columns are comparison-only.

`docs/reference/c070-airport-registry-exceptions.json` records the one secondary
cross-reference conflict: `IWA` maps to FAA NASR `KIWA` (Mesa Gateway), while the
retrieved OurAirports IATA row identifies `UUBI`. NASR remains authoritative; no
ICAO identifier is constructed by prefixing an IATA code.

Every registry entry explicitly keeps METAR, ATIS, runway, and NOTAM coverage
`UNKNOWN`. Registry membership does not enable any source or operational claim.
`scripts/build_c070_registry.py` can reproduce the compact registry and exception
report from saved public source CSVs; it performs no network activity itself.

The private DOMESTIC response is not an input to this repository and must never
be copied here.  The partitioner only reads an operator-supplied local file and
writes its result to stdout; publication is a separate reviewed action.
