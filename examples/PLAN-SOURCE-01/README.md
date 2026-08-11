# Granice pojedinačnog planskog prikaza

Ovaj direktorij sadrži dva nezavisna `EXPLAIN ANALYZE` JSON plana iz kojih su generisani PEV2 prikazi u Slici 2 rukopisa:

- `gac-plan.json` i `gac-query.sql` prikazuju da GAC plan udaljeni rad završava na `Foreign Scan` granici;
- `regional-plan.json` i `regional-query.sql` prikazuju zaseban regionalni Citus plan koji doseže `Custom Scan` i poslove na radnim čvorovima.

Planovi nisu dva sloja istog izvršenja i ne koriste se kao dokaz njihove korelacije. Njihova jedina uloga jeste pokazati da vizualizacija pojedinačnog PostgreSQL plana ne rekonstruiše cijelu GAC, FDW i Citus putanju. Povezani prije/poslije planski dokaz istog deklarisanog slučaja nalazi se u [`CASE-JOIN-01`](../CASE-JOIN-01/).

Regionalni plan je sanitizovan zamjenom privatnih runtime IP adresa oznakom `<runtime-private-ip>`. Planska struktura i izmjerene vrijednosti nisu mijenjane. Izvorne PEV2 veze i SHA-256 vrijednosti navedene su u [`manifest.json`](manifest.json).

SQL u ovom ilustrativnom primjeru koristi `now()`. Zbog toga artefakt nije dio tvrdnje o temporalnoj ponovljivosti glavnih eksperimenata niti se koristi za njihove numeričke rezultate.
