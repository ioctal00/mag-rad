# Konsolidovani audit ponovljivosti

**Status:** `PASS_WITH_DOCUMENTED_LIMITATIONS`. Audit je izveden samo nad zapakovanim artefaktima. Nisu pokrenuti Terraform, Ansible, SSH, SQL niti cloud API.

## Sta je moguce ponoviti

Paket omogucava nezavisnu provjeru SQL sadrzaja, konstrukcije korpusa, redoslijeda i ponavljanja, dataset profila, zbirnih rezultata, logickih indeksa i checksumova. Noviji skupovi imaju verzionisani generator, sjeme i vremenski oslonac. To je dovoljno za offline audit rezultata i za novi, ekvivalentno oblikovan infrastrukturni run.

Nije moguce dokazati bit-identicnu obnovu svakog historijskog runa. Nedostaju pojedini historijski Terraform planovi i runtime commitovi, puni row-level checksum dataseta te svi sirovi indeksi kasnijih panela. Apsolutno trajanje i identican plan nisu ponovljiv cilj zbog cachea, statistika, verzija i VPS suma.

## Infrastruktura

| Konfiguracija | Logicke regije | Cvorovi | Fizicka lokacija | Mreza |
| --- | --- | --: | --- | --- |
| N2 | EU, US i GAC | 7 | `ams` | jedan Vultr VPC |
| N3 | EU, US, APAC i GAC | 10 | `ams` | jedan Vultr VPC |
| stari `clean-run-v1` | EU, US i GAC | 7 | `ams`, `ewr`, `cdg` | stvarno vise lokacija |

Kasniji nazivi EU, US i APAC oznacavaju logicke Citus klastere. Pri tim eksperimentima WAN uslovi nisu prirodne medjuregionalne cloud putanje nego kontrolisani `tc/netem` profili nad kolociranim VPS instancama.

Terraform opisuje N2 sa sedam i N3 sa deset VPS cvorova. PostgreSQL je naveden kao major verzija 18, a Citus kao paketna porodica 14.0. Provider lock datoteke su ukljucene u ovaj paket, ali historijski primijenjeni plan/state nije. Javni `infra-plan` target trenutno ne daje kompletan neprimjenjujuci plan N2/N3 grafa.

Ansible cuva topoloske uloge i redoslijed konfiguracije, ali ne zakljucava svaki binarni ulaz. Verzija `ansible.posix`, tacni apt buildovi i dio udaljenih instalera ostaju runtime zavisnosti. Dataset load i FDW bootstrap su konvergentni, ali nisu distribuirano transakcijski; neuspjelo destruktivno ucitavanje ne vraca prethodni dataset.

## Dataset i skew

Svih 29 kataloskih profila postoji, a 29 SHA-256 vrijednosti odgovara. Siroki program koristi 13 profila, 869 uslova i 2.607 izvrsenja.

Tri mehanizma moraju se razlikovati:

1. `pilot-region-imbalanced-v1` daje priblizno 9:1 regionalni volumen;
2. `pilot-skew-heavy-v1` daje hot-tenant raspodjelu u oba regiona;
3. `pilot-region-local-skew-asymmetric-medium-v1` daje hot tenant-e samo u EU, dok je US uniforman.

Worker-skew osa ima 420 izvrsenja. Od toga 60 stvarno koristi treci, regionalno asimetricni profil. Profil ipak ne deklarira razlicit broj shardova ili genericki shard-placement skew. Worker/task neravnomjernost je izmjerena posljedica hot tenant-a i konkretnog rasporeda. Zavrsni DBA, N2/N3 memory i potvrdni action paneli ne pokrivaju worker-skew intervenciju.

Svih 418 grupa ima provjeren stressed/mitigated kontrast. Njih 397 podrzava sadrzajno poredjenje intervencije, dok preostalu 21 grupu cine prazne `current_date` no-work kontrole. One podrzavaju collector i result-equivalence ugovor, ali ne dokaz ucinka intervencije.

## Sweep i prikupljanje

Audit je ponovo izveo glavne brojeve: zajednički F19/F21 korpus 1.964; pressure 869 uslova puta tri ponavljanja, odnosno 2.607; DBA 60 uslova i 180 izvrsenja; kontrolisani N2/N3 180; potvrdni panel 60 uslova puta pet, odnosno 300; feedback loop 85 glavnih i 25 aggregate-exact izvrsenja.

Od 418 pressure grupa, 385 ima dva uslova i sest fizickih izvrsenja, a 33 cuvaju i medjustanje pa imaju tri uslova i devet izvrsenja. Ponavljanja imaju zaseban `execution_slot_id`; ista SQL datoteka zato nije isto sto i jedno fizicko izvrsenje. Williamsov raspored, shuffle sjemena, slotovi i odluke zapisane prije ishoda medjusobno su saglasni.

Collector audit pokriva 9 logickih arhiva sa 3.185 indeksiranih upita i 9 sirovih arhiva sa 3.145 fizickih pokusaja. Veze od upita preko GAC i regionalnog plana do worker/task fragmenata prolaze provjere roditeljskih identiteta.

Tri granice ostaju vazne. Regionalni `application_name` se postavlja, ali indexer ne filtrira svaki `auto_explain` dokument tim markerom, pa korelacija pretpostavlja serijsko kontrolisano izvrsavanje. Result signature nastaje naknadnim izvrsavanjem istog SQL-a, a ne u istom backend pozivu kao EXPLAIN. CPU, mreza, disk i VPS `steal` su host-level kontekst, ne query-level potrosnja.

## Pokretanje

```bash
make reproducibility-audit
make verify
```

Detaljni nalazi i validator svake oblasti nalaze se u poddirektorijima ovog direktorija. `summary.json` je autoritativni masinski sazetak.
