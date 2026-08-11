# Temporal validity audit v1

Ovaj paket je proizveden isključivo iz sačuvanih SQL iskaza, manifesta i
indeksa. Nije pokrenut SQL, regenerisan dataset niti refitovan model.

## Zaključak

Temporalna ponovljivost i unutrašnja valjanost nisu isti zahtjev. Kasniji
paneli i 397 sadržajnih
parova širokog programa imaju zamrznut ili vremenski nezavisan SQL. Preostalih
21 parova širokog programa
koriste `current_date`, vratili su prazan rezultat i vrijede samo kao
negativne kontrole bez aktiviranog rada.

Zajednički korpus modela F19 i F21 koristi pomični zidni sat:
1718 upita koristi `now()`, a
240
`current_date`. Izvorno mjerenje ipak ostaje upotrebljivo za deskriptivnu FCM
analizu jer je svaki sweep neposredno regenerisao dataset s istim zidnim
satom i nije bilo UTC promjene datuma. NMI tvrde grupe prema vremenskom
kvartilu iznosi 0.001865
za promovisani F19 i 0.001098
za historijski F21.
To nije dokaz nultog temporalnog uticaja, nego provjera da nema očite
konfuzije redoslijeda i klastera.

## Reprodukcija audita

```bash
make temporal-validity-audit
```

Glavni izlaz je `temporal_validity_audit.json`. CSV datoteke odvajaju
21 temporalnu negativnu kontrolu i osam zajedničkih FCM sweepova. Kontrolne sume su u
`checksums.sha256`.
