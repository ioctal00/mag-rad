# Rollback checklist

Ova lista se izvršava nakon svakog adaptivnog koraka, prije prihvatanja tranzicije i prije sljedeće odluke.

## Obavezno za svaki `action_id`

- [ ] Sačuvan je pre-action snapshot svih ciljanih GUC, FDW ili qdisc vrijednosti.
- [ ] Apply komanda odgovara tačno jednoj odluci iz zaključanog decision zapisa.
- [ ] Apply provjera je prošla na svakom ciljanom čvoru/edgeu.
- [ ] Nije izmijenjen dataset, indeks, kolokacija ni shard placement.
- [ ] Nakon tri ponavljanja izvršena je rollback komanda iz kataloga.
- [ ] Rollback provjera odgovara pre-action snapshotu, ne pretpostavljenom defaultu.
- [ ] Otvorene FDW konekcije su zatvorene/rebootstrapovane ako je mijenjana server opcija.
- [ ] `tc qdisc` i route-device status su vraćeni za svaki ciljani edge.
- [ ] Session GUC nije procurio u naredno stanje.
- [ ] SQL rewrite je vraćen na baseline template i iste parametre.
- [ ] Rollback artefakt i status povezani su sa `decision_id`.
- [ ] Neuspjeli rollback zaustavlja putanju i zabranjuje naredno izvršenje.

## Provjere po sloju

### GAC session

```sql
SHOW work_mem;
SHOW join_collapse_limit;
SHOW from_collapse_limit;
SHOW enable_hashagg;
SHOW jit;
SHOW max_parallel_workers_per_gather;
```

Vrijednosti poslije rollbacka moraju biti jednake pre-action snapshotu iste sesije ili mora biti potvrđeno da je izolovana sesija završena.

### Regionalne sesije

Na svakom aktivnom regionalnom koordinatoru remote probe mora potvrditi da su `work_mem`, `jit` i druge ciljane opcije jednake snapshotu. Nedostupan region nije uspješan rollback.

### FDW server

```sql
SELECT srvname, srvoptions
FROM pg_foreign_server
WHERE srvname = :foreign_server;
```

Poredi se cijeli sortirani option set. Ako opcija prije akcije nije postojala, rollback je mora ukloniti, a ne postaviti proizvoljan default.

### Mrežni edge

```text
python3 common-scripts/manage_network_pressure.py --action reset ...
tc qdisc show dev <route_device>
```

Status se poredi sa pre-action qdisc snapshotom za svaki ciljani edge. Ne prihvata se samo exit code reset komande.

### SQL rewrite

Baseline template, parametri i `logical_question_id` moraju biti vraćeni. Rezultatska ekvivalentnost rewritea provjerava se prije nego što se njegovo stanje prihvati kao epizoda.

## Fail-closed pravilo

`rollback_status != verified` blokira putanju. Ne pokušava se automatsko nastavljanje drugim actionom i ne prepisuje se prethodni outcome zapis.
