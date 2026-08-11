# Skupovi podataka

Ovaj direktorij je kratki ulaz u sintetičke skupove stvarno povezane s objavljenim SQL instancama. Potpuni ugovor svakog skupa nalazi se u [`dataset-index.csv`](dataset-index.csv), a YAML profili u [`sources/master-regimes/datasets/profiles/`](../sources/master-regimes/datasets/profiles/).

Skup podataka nije objavljen kao PostgreSQL dump. Ponovljiva konstrukcija sastoji se od DDL-a, generatora, profila, sjemena, `base_time_unix`, regionalnih raspona i shard ugovora.

## Šema i generator

- [`minimal_schema.sql`](../sources/citus-datagen/sql/minimal_schema.sql) je izvršivi DDL: tabele, indeksi, distribucijski ključevi, kolokacija i referentna tabela.
- [`current-schema-erd.svg`](../sources/citus-datagen/diagrams/current-schema-erd.svg) prikazuje isti ugovor kao ER dijagram.
- [`sources/citus-datagen/`](../sources/citus-datagen/) sadrži generator i naredbe za učitavanje.
- [`dataset-index.csv`](dataset-index.csv) povezuje eksperimentalni `dataset_id` sa profilom, sjemenom, vremenskim osloncem, brojem shardova i ugovorom regenerisanja.

DDL je zajednička osnova, dok YAML profil određuje obim, regionalne raspone, neravnomjernost, sjeme i `base_time_unix`. Zbog toga sam DDL nije dovoljan za ponavljanje konkretnog eksperimentalnog skupa.

## Profili koje je važno razlikovati

| Vrsta | Primjer profila | Značenje |
| --- | --- | --- |
| balansiran | `pilot-balanced-v1` | približno jednak regionalni obim i bez namjernog hot-tenanta |
| regionalno nebalansiran | `pilot-region-imbalanced-v1` | različit obim redova između EU i US |
| globalni hot-tenant | `pilot-skew-heavy-v1` | neravnomjerna frekvencija tenant ključeva u cijelom skupu |
| lokalno asimetričan | `pilot-region-local-skew-asymmetric-medium-v1` | EU hot-tenant opterećenje uz uniformniji US; worker/task neravnomjernost se mjeri iz izvršenja |
| N2/N3 topology isolation | `topology-isolation-*-n2/n3-v1` | upareni profili za kontrolisanu promjenu broja logičkih regiona |

Lokalno asimetričan profil ne mijenja broj shardova po workeru. Oznaka worker skew odnosi se na opaženu neravnomjernost redova, taskova ili vremena rada koja nastaje iz hot-tenant podataka i stvarnog placementa.

Vremenski presjeci i poznati stariji izuzeci objedinjeni su u [`temporal-validity-audit-v1`](../releases/temporal-validity-audit-v1/). Glavni noviji paneli koriste verzionisani `base_time_unix`; zajednički stariji korpus modela F19 i F21-dev ima slabiji temporalni ugovor i u radu se tumači samo kao arhivirani deskriptivni dokaz.
