# Audit Ansible i konfiguracijske ponovljivosti

## Obuhvat i postupak

Audit je izveden nad zapakovanim izvorima u `sources/master-regimes-infra`. Nisu pokretani Ansible, SSH, Terraform, cloud API-ji niti konekcije prema bazi. Nisu citani generisani `ansible/group_vars/all.yml`, generisani inventar, Terraform state, `.env`, kljucevi ili tajne.

Offline validator koristi eksplicitnu listu dozvoljenih datoteka i provjerava njihov konfiguracijski ugovor. Po zelji se moze proslijediti i zaseban izvorni checkout radi SHA-256 poredjenja. Pokretanje pakovanog audita:

```bash
python3 reproducibility/audits/ansible/audit.py \
  --source sources/master-regimes-infra \
  --package sources/master-regimes-infra \
  --output reproducibility/audits/ansible/findings.json \
  --strict
```

Rezultat ovog prolaza:

| Provjera                          | Ishod |
| --------------------------------- | ----: |
| Provjerene kriticne datoteke      |    39 |
| Prolazne strukturne provjere      |     3 |
| Upozorenja o runtime zavisnostima |     7 |
| Nalazi visokog prioriteta         |     3 |
| Nalazi srednjeg prioriteta        |     5 |
| Nalazi niskog prioriteta          |     2 |

Masinski citljiv rezultat nalazi se u `findings.json`.

## Glavni zakljucak

Zapakovani izvor vjerno cuva deklarativnu namjeru infrastrukture: topoloske uloge, broj radnih cvorova, PostgreSQL major verziju, Citus paketnu porodicu, redoslijed uloga, renderiranje i eksperimentalne orkestratore. To je ponovljiva konfiguracija na nivou izvornog ugovora.

Isti repozitorij, medjutim, nije dovoljan za bit-po-bit obnovu izvornog runtimea. Tacni Ansible i `ansible.posix`, Debian buildovi PostgreSQL/Citus paketa, sadrzaj udaljenih instalacijskih skripti, konkretni Git commit generatora, Terraform adrese/VPC vrijednosti i pocetno stanje `tc` discipline ostaju vanjski ulazi. Zato treba razlikovati:

| Ponovljivo iz izvora | Zavisno od runtimea ili vanjskog stanja |
| --- | --- |
| logicke uloge GAC/EU/US/APAC | javne i privatne IP adrese |
| dva radnika po regionu u kanonskim N2/N3 konfiguracijama | konkretni VPC identitet i provider dodjela |
| PostgreSQL 18 i Citus 14.0 paketna porodica | tacan Debian paketni build |
| renderiranje grupa i Citus clanstva | verzija Ansible corea i kolekcija |
| dataset profil, sjeme, vremenski oslonac i regionalni override | stvarni commit generatora ako nije unaprijed zakljucan |
| audit broja redova, shardova i hot-tenant rasporeda | potpuna jednakost svih redova nakon novog ucitavanja |
| uklanjanje eksperimentalnog root qdisc-a | obnova proizvoljnog ranijeg qdisc stabla |

## Playbookovi i uloge

`site.yml` jasno razdvaja opcu pripremu hosta, PostgreSQL/Citus cvorove, koordinatore, analiticki GAC i pomocne alate. PostgreSQL/Citus uloga provjerava postojanje baze i role, kreira ekstenzije te aktivno uklanja medjuregionalne radnike sa pogresnog koordinatora prije registracije lokalnih radnika (`ansible/roles/postgresql_citus/tasks/main.yml:508`, `ansible/roles/postgresql_citus/tasks/main.yml:588`). To je dobra konvergencija efektivnog topoloskog stanja.

Stroga Ansible idempotencija ipak nije dokazana. Promjena lozinke, vlasnistva i pojedini grantovi izvrsavaju se pri svakom prolazu, a Git i build koraci mogu ponovo prijaviti promjenu. Marker Citus repozitorija nakon prvog prolaza sprecava ponovno izvrsavanje eventualno izmijenjenog instalera (`ansible/roles/postgresql_citus/tasks/main.yml:52`). Uloge su zato uglavnom konvergentne, ali nije garantovan drugi prolaz bez promjena.

Destruktivna reinstalacija PostgreSQL-a odvojena je u poseban playbook i trazi eksplicitnu potvrdu. To je dobar sigurnosni obrazac, ali nije zamjena za snapshot podataka ili transakcijski rollback dataset ucitavanja.

## Verzije PostgreSQL-a, Citusa i alata

Kanonske N2 i N3 konfiguracije navode PostgreSQL `18` i paket `postgresql-18-citus-14.0` (`configs/systems/eu-us-gac-vps.yml:21`, `configs/systems/eu-us-apac-gac-vps.yml:21`). `verify-citus.yml` provjerava PostgreSQL major, prisutnost paketa, apt hold, Citus `14.0` i aktivne radnike (`ansible/playbooks/verify-citus.yml:24`, `ansible/playbooks/verify-citus.yml:71`).

Ovo zakljucava porodicu proizvoda, ali ne i tacan binarni build:

1. `ansible.posix` nema verziju u `ansible/requirements.yml:2`.
2. Ansible core nije dio Python locka, a wrapper koristi sistemski Python (`common-scripts/run_ansible.sh:20`).
3. Shim importuje privatni Ansible 2.21 RPC modul (`common-scripts/ansible_shim.py:30`), pa je osjetljiv na verziju.
4. Apt instalira imena paketa bez `=verzija`, a zatim drzi upravo preuzeti build (`ansible/roles/postgresql_citus/tasks/main.yml:79`).
5. PGDG kljuc, Citus repo skripta i `uv` installer preuzimaju se sa promjenjivih URL-ova bez sadrzajnog checksum ugovora.

Najozbiljnija neujednacenost izvornog koda alata je `citus-datagen`. Konfiguracija koristi promjenjivu granu `pivot/fcm-results-rework` (`configs/systems/eu-us-gac-vps.yml:113`). Uloga upucuje na `make repo-sync-datagen`, ali Makefile takav cilj ne sadrzi (`ansible/roles/citus_datagen/tasks/main.yml:107`, `Makefile:3`). Nasuprot tome, `psql-benchmarks` sync biljezi lokalni HEAD i provjerava isti udaljeni HEAD (`common-scripts/sync_remote_repo.py:91`, `common-scripts/sync_remote_repo.py:265`).

Zavrseni dataset manifest biljezi stvarni udaljeni datagen commit, sto omogucava audit arhiviranog ucitavanja. Svjezi replay ga ipak ne bira automatski.

## Topologija i inventar

Renderiranje iz YAML-a je deterministicno za logicke uloge i postavke, uz izuzetak vremenske oznake manifesta. N2 konfiguracija definise EU i US sa po dva radnika, dok N3 dodaje APAC sa dva radnika. Sve tri logicke regije koriste `vultr_region: ams`; APAC komentar eksplicitno navodi da je to logicka regija kolocirana radi kontrolisanih mreznih profila (`configs/systems/eu-us-apac-gac-vps.yml:58`).

Konkretni inventar nastaje iz trenutnog `terraform output -json` (`ansible/inventory/terraform_inventory.py:29`). Izuzetak ili neispravan JSON vracaju prazan izlaz (`ansible/inventory/terraform_inventory.py:35`). Glavne lifecycle skripte to djelimicno zatvaraju:

- N2 wrapper zahtijeva prisustvo DB i analytics grupa (`common-scripts/up_eu_us_gac_vhp_shared_vpc.sh:236`).
- N3 wrapper zahtijeva tacno tri APAC DB cvora i zadrzan GAC (`common-scripts/extend_eu_us_gac_with_apac.sh:160`).

Direktna ili genericka upotreba inventory skripte i dalje moze dobiti prazan inventar bez jasne greske. IP adrese, VPC ID/CIDR i SSH/CIDR vrijednosti nisu izracunljive samo iz repozitorija. One su opravdano runtime ulazi, ali moraju biti sacuvane u netajnom manifestu zavrsenog eksperimenta ako su potrebne za provjeru provenancea.

## Dataset apply, regionalni skew i bootstrap

Loader podrzava regionalno razlicite raspodjele. `region_distribution()` se primjenjuje prije formiranja datagen okruzenja (`common-scripts/apply_dataset_profile.py:950`), a test eksplicitno pokriva EU sa heavy skew profilom i US koji nasljedjuje balansirani profil (`tests/test_apply_dataset_profile.py:22`). To dokazuje sposobnost konfiguracije da modelira slucaj u kojem jedan region ima skew, a drugi nema.

Ovaj Ansible subaudit ne moze tvrditi da je takav profil stvarno koristen u odredjenom glavnom korpusu. Dataset profili i arhivirani run manifesti koji daju taj odgovor nalaze se izvan dodijeljenog read-only obuhvata. To mora potvrditi zasebni dataset/corpus audit preko `dataset_profile.yml`, `dataset_load_manifest.json`, `effective_distribution` i worker-placement artefakata.

Pozitivni dio dataset ugovora je detaljan. Load manifest cuva profil i njegov SHA-256, sjeme, vremenski ugovor, commit generatora, broj redova, shard raspodjelu, hot tenant mapiranje i hash tih auditnih komponenti (`common-scripts/apply_dataset_profile.py:1032`). Ugovor, medjutim, eksplicitno navodi da nema row-level checksum (`common-scripts/apply_dataset_profile.py:703`). Ponovljivost svih redova zato zavisi od istog generatora, profila, sjemena, verzija i deterministickog ponasanja baze.

Dataset rollback je ogranicen. Trap vraca privremeni `.env` i prekida proces, ali `reset-and-load` je destruktivan (`common-scripts/apply_dataset_profile.py:993`). Ako ucitavanje stane nakon brisanja tabela, prethodni dataset se ne vraca. Obavezan post-load audit zato mora biti admission gate prije svakog sweepa.

FDW bootstrap ima slicnu granicu atomarnosti. Regionalni view se prvo kreira ili zamjenjuje, pa se zatim odvojeno pokrece GAC `fdw-bootstrap` (`common-scripts/run_gac_fdw_bootstrap.py:117`, `common-scripts/run_gac_fdw_bootstrap.py:323`). Prekid moze ostaviti razlicite revizije regionalnog i GAC stanja. Rerun je predvidjeni oporavak, ali nedostaje jedinstvena zavrsna provjera svih regiona i GAC objekata.

## Reset, rollback i drift

Mrezna intervencija biljezi `qdisc` i ping prije i poslije, a reset se izvodi u oba smjera. Ipak, reset radi `tc qdisc del ... root` (`common-scripts/manage_network_pressure.py:144`). Sacuvano prethodno qdisc stablo se ne rekonstruiše. U sweep `finally` bloku reset se poziva sa `allow_failure=True` (`common-scripts/run_database_sweep.py:1454`).

Ugovor je zato ponovljiv samo uz eksplicitni preduvjet da je baseline bez eksperimentalnog root qdisc-a. Na hostu sa legitimnim prethodnim traffic-control stanjem taj postupak nije vjeran rollback. Zaostali netem ili neuspjeli reset trebaju biti hard stop, ne samo auditni status.

`single-eu-drift-check` poredi renderovane `terraform.tfvars` i `group_vars/all.yml` (`Makefile:346`). `verify-citus.yml` provjerava osnovnu verziju i topologiju. Nisu objedinjeno provjereni svi GUC-ovi, TLS/PgBouncer, FDW opcije, commitovi alata, dataset snapshot, mrezni baseline i time-service. `probe_lab_environment.py` moze oznaciti odstupanje kao `attention`, ali nije obavezni fail-closed gate (`common-scripts/probe_lab_environment.py:180`).

Vremenska korelacija nije Ansible-managed NTP ugovor. Collector umjesto toga kalibrise sat svakog cvora tokom prikupljanja i cuva kalibraciju (`common-scripts/run_query_collection.py:1456`, `common-scripts/run_query_collection.py:1986`). To je koristan dokaz za vec zavrsen run, ali ne garantuje jednaku host clock konfiguraciju pri novom deployu.

## Prioriteti za zatvaranje

1. Zakljucati Ansible core, `ansible.posix`, OS image, tacne apt buildove i checksumove udaljenih instalera.
2. Uvesti commit-pin i stvarni exact-sync put za `citus-datagen`.
3. Gateovati eksperiment na post-load dataset audit; za potpuni rollback koristiti DB snapshot ili replacement-database obrazac.
4. Proglasiti no-root-qdisc kao obavezan mrezni baseline i reset failure kao sigurnosni stop.
5. Objediniti read-only live-state audit za GUC, FDW, tool commit, dataset, tc/netem i vrijeme.
6. U dataset/corpus auditu utvrditi koji je regionalni distribution profil stvarno koristen u svakom objavljenom korpusu.

## Granica zakljucka

Audit podrzava tvrdnju da je konfiguracijska namjera rada dobro arhivirana i da su kanonske topologije, uloge i orkestracijski ugovori dostupni za pregled. Ne podrzava tvrdnju da se iz paketa bez dodatnih pinova moze automatski obnoviti identican cloud raspored, identican binarni software, identican dataset na nivou svakog reda ili identicno runtime stanje. To su odvojeni nivoi ponovljivosti i trebaju biti tako predstavljeni u paketu za provjeru i ponovno izvođenje te u rukopisu.
