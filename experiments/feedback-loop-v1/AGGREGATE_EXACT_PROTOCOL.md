# Zamrznuti agregacijski dodatak

Ovaj dodatak zatvara ranije zaustavljenu agregacijsku putanju bez promjene fiksnih RQ-ova, hipoteza, šest domena ili formule relativnog profila. Koristi tačan jednoredni rezultat `COUNT/MIN/MAX`; numerička tolerancija nije uvedena.

Prije prvog izvršenja zamrznuti su SQL par, tri intervencije, njihove hipoteze, redoslijed, broj ponavljanja i tri odvojene ose ishoda. Katalogizovane, ali neizvršene intervencije nisu dio rezultata ovog dodatka.

## Stanja

```text
A: raw EU+US redovi, fetch_size=1000
B: raw EU+US redovi, fetch_size=10000
C: regionalni COUNT/MIN/MAX, fetch_size=10000
D: stanje C uz 10 ms EU egress delay
R0': raw EU+US redovi, fetch_size=1000, bez tc profila
```

Stanja A-D izvršavaju se po pet puta u unaprijed zaključanom Williamsovom redoslijedu. R0' se zatim izvršava pet puta nakon eksplicitnog rollbacka. Ukupno se planira 25 potpuno instrumentovanih izvršenja.

## Odvojene ose ishoda

Jedinstvena oznaka `mixed` ostaje samo kompatibilni historijski zapis. Glavna interpretacija koristi:

1. valjanost rezultata: `equivalent` ili `non_equivalent`;
2. end-to-end učinak: `positive`, `negative`, `no_material_change` ili `indeterminate`;
3. fizičku tranziciju: `predominantly_favorable`, `predominantly_adverse`, `mixed`, `sparse` ili `unavailable`.

Jasan runtime smjer ne briše konfliktne domenske komponente. Fizička oznaka ne predstavlja kauzalni doprinos niti univerzalnu ozbiljnost pritiska.
