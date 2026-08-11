# master-regimes-infra

Terraform/Ansible infrastruktura za geo-distribuirani Citus + GAC setup.

Ovaj repo polazi od sanitizovane stare implementacije, ali novi cilj nije samo "podići iste mašine". Cilj je kontrolisati drift između Terraform-a, Ansible-a i run manifesta.

## Layout

| Putanja | Namjena |
| --- | --- |
| `configs/systems/` | Jedan topološki source-of-truth po sistemu. |
| `terraform/` | Stari Terraform envs/modules, zadržani kao deploy podloga. |
| `ansible/` | Stari Ansible playbook/roles, zadržani kao provisioning podloga. |
| `generated/` | Lokalni renderi, Terraform planovi i run artefakti. Gitignored; struktura je opisana u `generated/README.md`. |
| `src/master_regimes_infra/` | Početni render/validate CLI. |
| `pki/` | Samo PKI dokumentacija i lokalno generisani materijal. |

## Brzi start

Ne radi direktno sa `configs/systems/...` putanjama osim kada mijenjas samu topologiju. Za poznate infrastrukturne korake koristi scenario targete iz Makefile-a.

```bash
make topology-list
make generated-tree
make config-validate TOPOLOGY=eu-vps-single
make configure-env-check
make config-render TOPOLOGY=eu-vps-single
```

Trenutni kanonski fajlovi su opisani u `configs/systems/README.md`. Pravila kada promjena zahtijeva Terraform, Ansible ili samo env reload su u `docs/configuration-lifecycle.md`.

## EU VPS klaster

Single-cluster setup ostaje podržan za izolovane regionalne probe: 1 EU coordinator + 2 EU workera, bez GAC-a. Runbook je u `docs/eu-vps-single-cluster.md`.

Trenutna parser/collector faza rada koristi proširenu EU+US+GAC topologiju iz sljedeće sekcije.

Prvi put popuni lokalne tajne i operator vrijednosti:

```bash
make configure-env
```

Nakon toga je podizanje pocetne VPS infrastrukture jedna komanda:

```bash
make eu-vps-single-up
```

Za gasenje:

```bash
make eu-vps-single-down
```

`eu-vps-single-up` pokazuje na `configs/systems/eu-vps-single.yml` i izvrsava fiksni redoslijed: env check, doctor, render/install, drift check, Terraform init/plan/apply, cekanje cloud-init-a, inventory, Ansible provisioning, verifikaciju i manifest. Terraform `apply` koristi snimljeni plan i `-auto-approve`, pa nema dodatnog `yes` prompta.

`make configure-env` cuva lokalne SSH vrijednosti i lokalne access CIDR allowliste, tako da system YAML ostaje pogodan za GitHub. Moze sacuvati i `MASTER_REGIMES_GIT_PAT`, koji Ansible koristi za read-only HTTPS clone fallback privatnih repozitorija na remote serverima. PAT se cita iz environmenta i ne upisuje se u git.

`make configure-env-check` pita samo za vrijednosti koje nisu vec postavljene u shellu ili `~/.config/master-regimes-infra/env`. Makefile automatski ucitava taj env fajl kroz `BASH_ENV` za svoje recipe shell komande.

Kada zelis rucno pregledati plan prije apply-a, koristi razdvojeni tok:

```bash
make eu-vps-single-plan
make eu-vps-single-apply
```

## EU VPS + US VPS + GAC smoke topologija

Kada su potrebni EU Citus, US Citus i analytics/GAC čvor, koristi scenario targete za `configs/systems/eu-us-gac-vps.yml`:

```bash
make eu-us-gac-vps-up
make eu-us-gac-vps-ping
make eu-us-gac-vps-ansible
make eu-us-gac-vps-tools-sync
```

`make eu-us-gac-vps-up` podiže oba Terraform stacka: `terraform/envs/eu` za EU + GAC + web portal host i `terraform/envs/us` za logički US Citus klaster. Fizički su oba regionalna klastera u `ams`; `us` je logički region za eksperimente, a WAN latencija/jitter/loss se po potrebi uvode kontrolisano kroz `tc netem`.

Model mašina se bira centralno u `configs/systems/eu-us-gac-vps.yml`, kroz:

```yaml
compute_profiles:
  vps:
    resource_type: instance
    coordinator_plan: vhf-1c-2gb
    worker_plan: vhf-1c-2gb
    analytics_plan: vhf-1c-2gb
  baremetal:
    resource_type: bare_metal
    coordinator_plan: vbm-6c-32gb
    worker_plan: vbm-6c-32gb
    analytics_plan: vbm-6c-32gb

active_profile: vps
```

Za jeftini VPS run koristi se `active_profile: vps`, trenutno sa Vultr planom `vhf-1c-2gb` za koordinatore, workere i analytics/GAC čvor. Ranije korišteni bare-metal profil je zabilježen kao `vbm-6c-32gb`; za povratak na njega promijeni `active_profile` na `baremetal` i prije apply-a pregledaj Terraform plan.

Trenutna brza eksperimentalna varijanta stavlja logičke EU, US i GAC čvorove u isti Vultr VPC u `ams`. To namjerno nije geografski razdvojen deployment; koristi se da se ubrza plan/parser rad, a regionalna latencija se kasnije kontroliše eksplicitno.

### cloudb-web portal

`configs/systems/eu-us-gac-vps.yml` uključuje i mali `web_portal` VPS u istom VPC-u. Taj čvor drži:

- `nginx` kao javni ulaz;
- tri Pgweb instance:
  - `/gac/` za analytics/GAC PostgreSQL,
  - `/eu/` za EU coordinator,
  - `/us/` za logički US coordinator;
- `/viewer/` za `regime-diagnosis-viewer`.

Portal ne otvara PostgreSQL javno. Pgweb se spaja kroz VPC/private IP adrese i koristi read-only PostgreSQL role `prof_demo`. U cloud deploymentu nginx je jedini javni Basic Auth guard za `/viewer/`, `/gac/`, `/eu/` i `/us/`; viewer zadržava vlastiti `.env` auth guard samo za standalone/local pokretanje bez nginx-a ispred njega.

Portal je dio istog lifecycle-a kao ostala EU+US+GAC infrastruktura:

- `make eu-us-gac-vps-up` kreira portal VPS kroz Terraform, čeka SSH/cloud-init, instalira potrebne pakete i deploy-a aplikacije kroz `cloudb_web` Ansible role.
- `make eu-us-gac-vps-down` ruši US stack, zatim EU stack, uključujući Terraform-managed `web_portal` instancu i shared VPC.
- `common-scripts/recreate_eu_us_gac_vhp_shared_vpc.sh` radi isti full lifecycle tok i nakon inventory generisanja eksplicitno provjerava da postoji `web_portals` host kada je `web_portal.enabled: true`.

Za običan update aplikacijskog koda ne treba Terraform niti rušenje hosta; tada koristi samo `make eu-us-gac-vps-apps-deploy`.

Env vrijednosti koje treba popuniti preko `make configure-env` ili lokalnog `~/.config/master-regimes-infra/env`:

```bash
MASTER_REGIMES_DEMO_DB_PASSWORD
MASTER_REGIMES_CLOUDB_WEB_AUTH_USERS
MASTER_REGIMES_VIEWER_AUTH_USERS
```

Format auth varijabli je:

```text
mentor:<password>,profesor1:<password>,profesor2:<password>
```

Ako je infrastruktura već podignuta, a želiš samo osvježiti portal/read-only korisnika:

```bash
make eu-us-gac-vps-cloudb-web-deploy
```

Za normalan CI/CD tok aplikacija, source-of-truth je sada:

```text
../master-regimes-apps/apps/cloudb-web
../master-regimes-apps/apps/regime-diagnosis-viewer
```

`web_portal.app_source_mode: git` znači da portal host koristi remote checkout:

```text
/opt/master-regimes-apps
```

Nakon što promijeniš aplikaciju i push-aš `master-regimes-apps`, update na serveru je:

```bash
make eu-us-gac-vps-apps-deploy
```

Ovaj target radi `git pull`/checkout na portalu, regeneriše `.env`, osvježi nginx/htpasswd i restartuje Docker servise. Ako je repo privatan, postavi `MASTER_REGIMES_GIT_PAT` i `MASTER_REGIMES_GIT_USERNAME` kroz `make configure-env`.

Ako lokalno postoji viewer snapshot:

```text
../master-regimes-apps/apps/regime-diagnosis-viewer/public/diagnosis-data.json
```

role ga kopira na portal poslije Git checkouta. Taj JSON je generisan iz ranijih `master-regimes`/`master-regimes-infra` run artefakata i nije commitan u Git. Za osvježavanje statičkih primjera prvo pokreni:

```bash
cd ../master-regimes-apps/apps/regime-diagnosis-viewer
npm run prepare-data:local
```

pa zatim `make eu-us-gac-vps-apps-deploy`.

Javni IP portala:

```bash
terraform -chdir=terraform/envs/eu output -raw web_portal_public_ip
```

Produkcijski naziv portala je podešen kroz `web_portal.server_name`, trenutno:

```text
thesis-demo.example.org
```

Trenutni portal koristi Cloudflare proxy i Cloudflare Origin certificate:

```yaml
web_portal:
  tls:
    provider: cloudflare_origin
    cloudflare_proxy: true
    origin_cert_local_path: pki/cloudflare/origin.pem
    origin_key_local_path: pki/cloudflare/origin.key
```

Certifikat i privatni ključ ostaju lokalni secret fajlovi i ne idu u Git. Ansible ih kopira na portal u:

```text
/etc/ssl/cloudb-web/cloudflare-origin.pem
/etc/ssl/cloudb-web/cloudflare-origin.key
```

Kad je `cloudflare_proxy: true`, render automatski dodaje Cloudflare IPv4 CIDR-ove u `web_ipv4_cidrs`, tako da Vultr firewall i UFW dozvole Cloudflare edge konekcije prema portalu na 80/443. U Cloudflare dashboardu SSL/TLS mode treba biti `Full` ili `Full (strict)`, ne `Flexible`.

Alternativno, ako se Cloudflare proxy isključi i želiš javni Let's Encrypt certifikat direktno na origin-u, koristi:

```yaml
web_portal:
  tls:
    provider: letsencrypt
```

Za Let's Encrypt HTTP-01 izdavanje domena tada mora javno isporučiti:

```text
http://thesis-demo.example.org/.well-known/acme-challenge/<token>
```

sa web portal hosta. Najjednostavnije je da DNS A zapis za `thesis-demo.example.org` pokazuje na `web_portal_public_ip` bez proxyja dok se certifikat izdaje. Taj fallback ne koristi poseban email env; certbot se pokreće u non-interactive modu bez email registracije.

Nakon uspješnog TLS podešavanja rute su:

```text
https://thesis-demo.example.org/viewer/
https://thesis-demo.example.org/gac/
https://thesis-demo.example.org/eu/
https://thesis-demo.example.org/us/
```

Ako certifikat još nije izdat, privremeno rade iste rute preko HTTP-a ili direktno preko IP-a:

```text
http://<web_portal_public_ip>/viewer/
http://<web_portal_public_ip>/gac/
http://<web_portal_public_ip>/eu/
http://<web_portal_public_ip>/us/
```

Za potpuno rušenje trenutnog EU/US/GAC stanja i ponovno podizanje ove shared-VPC varijante postoji neinteraktivna skripta. Ne pita za `yes`; traži samo eksplicitnu env potvrdu prije starta:

```bash
MASTER_REGIMES_RECREATE_CONFIRM=destroy-and-recreate \
  common-scripts/recreate_eu_us_gac_vhp_shared_vpc.sh
```

Skripta ruši `us` stack prije `eu`, zatim kreira `eu` + GAC, čita EU `vpc_id/vpc_cidr`, kreira logički `us` stack prikačen na isti VPC, čeka SSH i cloud-init na svim čvorovima, generiše inventory, pokreće Ansible za `eu:us` i verifikuje Citus. Planovi u tekstualnom obliku ostaju u `generated/tfplans/eu-us-gac-shared-vpc/`.

Za dnevno čuvanje novca koristi odvojene lifecycle skripte umjesto recreate skripte.

Potpuno gašenje ove topologije:

```bash
MASTER_REGIMES_DESTROY_CONFIRM=destroy-eu-us-gac-vhp-shared-vpc \
  common-scripts/destroy_eu_us_gac_vhp_shared_vpc.sh
```

Ponovno podizanje iste topologije:

```bash
MASTER_REGIMES_UP_CONFIRM=create-eu-us-gac-vhp-shared-vpc \
  common-scripts/up_eu_us_gac_vhp_shared_vpc.sh
```

Napomena: lifecycle helper imena i confirmation stringovi i dalje sadrže historijski `vhp` naziv radi kompatibilnosti. Stvarni model mašine se ne bira iz naziva skripte, nego iz `compute_profiles` / `active_profile` u system YAML-u.

`destroy` ruši `us` prije `eu` da ne ostane US stack zakačen na EU VPC. Zatim provjerava da su Terraform state-ovi prazni; ako EU VPC još javlja attachovane servere, skripta sačeka 60 sekundi i jednom ponovi EU destroy. `up` prvo kreira `eu` + GAC + web portal, zatim prikači `us` na isti EU VPC i ponovo pokrene Ansible provisioning/verify za `eu:us`.

`eu-us-gac-vps-tools-sync` je namijenjen brzom eksperimentalnom ciklusu kada lokalni `psql-benchmarks` ima izmjene koje još nisu pushane. Target radi:

1. čeka SSH/cloud-init,
2. generiše inventory,
3. rsync-a lokalni `../psql-benchmarks` na DB i analytics čvorove,
4. pokreće samo `psql_benchmarks` Ansible tag,
5. preskače Git update da rsync sadržaj ne bude pregažen,
6. osvježava `.env`, executable bitove i `uv sync`.

Za FDW/GAC bootstrap:

```bash
make eu-us-gac-vps-fdw-bootstrap FDW_BOOTSTRAP_REGION=eu
make eu-us-gac-vps-fdw-bootstrap FDW_BOOTSTRAP_REGION=us
make eu-us-gac-vps-etl-bootstrap GAC_ETL_BOOTSTRAP_REGION=eu
```

Za multi-region FDW query-je bootstrapaj oba regionalna servera (`eu` i `us`). Single-region debug smije namjerno koristiti samo jedan region.

`fdw-bootstrap` podržava eksplicitne `postgres_fdw` server opcije. Corpus runtime katalog ih prenosi kroz generated sweep polje `runtime_configs[].fdw_server_options`; npr. `fetch_size=100` ili `fetch_size=10000`. Kada database-sweep runtime config sadrži `fdw_server_options`, runner radi FDW rebootstrap prije pokretanja query sweepa za tu runtime grupu. `psql_variables.FETCH_COUNT` ostaje samo query/audit context i ne zamjenjuje FDW server opciju.

Za GAC query-sweep nad analytics čvorom:

```bash
make single-eu-query-sweep \
  TOPOLOGY=eu-us-gac-vps \
  QUERY_SWEEP_LABEL=fdw-smoke \
  QUERY_SWEEP_INSTANCE_MANIFEST=../master-regimes/generated/workloads/<suite-id>/<render-id>/instance_manifest.csv \
  QUERY_SWEEP_MAX_INSTANCES=1 \
  QUERY_SWEEP_TARGET_GROUP=analytics_clients \
  QUERY_SWEEP_FDW_AUTO_EXPLAIN=true \
  QUERY_SWEEP_CITUS_EXPLAIN_ALL_TASKS=false
```

Eksperimentalni PostgreSQL korisnik za `psql-benchmarks`, GAC FDW bootstrap i regionalni `auto_explain` je `postgres`. Aplikacijski korisnici `app` i `analytics` ostaju kontekst za aplikacijske/legacy puteve, ali nisu default za master-regimes eksperimentalnu kolekciju jer regionalni plan/task evidence zahtijeva jednake privilegije kroz EU, US i GAC.

Za FDW/GAC eksperimente preferiraj `QUERY_SWEEP_FDW_AUTO_EXPLAIN=true`. Tada wrapper privremeno uključuje regionalni `auto_explain` za FDW remote usera, izvršava GAC query i skida regionalne PostgreSQL log delte u `regional-auto-explain/`. Ovo je **observed remote execution evidence**.

Bez `QUERY_SWEEP_FDW_AUTO_EXPLAIN=true`, kolekcija može snimati samo dijagnostičke regionalne remote plan probe kada glavni JSON plan sadrži `Remote SQL`. Ti artefakti su pod `plans/remote/` i navedeni su u `execution_manifest.json` pod `fdw_remote_plan_probe`, ali su fallback/debug evidence jer ponovo izvršavaju remote SQL kao poseban query.

Nakon query sweepa generiši normalizovani parser/ML ulaz u `master-regimes`:

```bash
cd ../master-regimes
uv run master-regimes index-query-sweep \
  --sweep-dir ../master-regimes-infra/generated/runs/query-sweeps/<sweep-id>
```

`instance_manifest.csv` sada može nositi corpus/workload metadata kao `logical_question_id`, `execution_strategy`, `expected_regime_targets`, `runtime_sensitivity`, `corpus_id` i `corpus_cell_id`. Infra ne tumači te vrijednosti kao model signale; samo ih mora očuvati kroz `query_sweep_manifest.json`, `_index/query_runs.csv` i `_index/corpus_cells.csv`.

Za historijski EU+GAC parser/collector readiness referentni clean smoke je database sweep:

```text
generated/runs/database-sweeps/
  20260623T010716Z-two-profiles-five-shapes-gac-feature-smoke/
```

Taj smoke dokazuje da kolekcija, FDW remote-plan probe, plan tree index i database-level `_index` rade. Ne koristi se kao režimski dokaz jer su smoke dataset profili premali i jer sadašnji multi-region evidence koristi regionalni `auto_explain` kao preferirani izvor.

Naredni režimski pilot koristi veće pilot profile:

```bash
make single-eu-database-sweep \
  TOPOLOGY=eu-us-gac-vps \
  DATABASE_SWEEP_CONFIG=configs/sweeps/gac-regime-pilot-v1.yml \
  DATABASE_SWEEP_LABEL=gac-regime-pilot-v1
```

Za corpus-aware run ne pokreći ručno svaki generated sweep. Prvo u `../master-regimes` renderuj corpus, zatim u ovom repozitoriju pokreni wrapper:

```bash
make eu-us-gac-vps-corpus-run \
  CORPUS_EXECUTION_PLAN=../master-regimes/generated/corpus/pre-us-pilot/corpus_execution_plan.yml \
  CORPUS_RUN_LABEL=pre-us-pilot \
  CORPUS_RUN_DRY_RUN=true
```

`CORPUS_RUN_DRY_RUN=true` samo validira plan i piše corpus-level manifest. Bez dry-run moda wrapper sekvencijalno poziva postojeći `run_database_sweep.py` za svaku grupu iz `corpus_execution_plan.yml`, tako da svaka grupa i dalje ima normalan database-sweep output i `_index`.

Corpus manifest može definisati `execution_budget.hard_timeout_seconds`. Taj budžet se prenosi u generated sweep config i dalje do svakog query collection runa. Ako query pređe budžet, dobija `execution_status=timeout`, artefakti koji postoje ostaju sačuvani, a sweep nastavlja sa narednom instancom.

Za rerun ne briši prvi output. Pokreni novi fizički corpus run sa istim logičkim ID-om i, po potrebi, većim timeoutom u corpus manifestu ili generated sweep configu:

```bash
make eu-us-gac-vps-corpus-run \
  CORPUS_EXECUTION_PLAN=../master-regimes/generated/corpus/pre-us-pilot/corpus_execution_plan.yml \
  CORPUS_RUN_LABEL=pre-us-pilot-rerun-01 \
  CORPUS_LOGICAL_RUN_ID=pre-us-pilot \
  CORPUS_RERUN_OF=<prethodni-corpus-run-id>
```

Zatim izgradi logički status preko svih pokušaja:

```bash
make corpus-run-index CORPUS_LOGICAL_RUN_ID=pre-us-pilot
```

To piše `corpus_attempts.csv`, `group_attempts.csv`, `query_attempts.csv`, `resolved_query_status.csv` i kanonski merged `_index/` pod `generated/runs/corpus-sweeps/_logical-runs/<logical-run-id>/`.

Logical `_index/` bira najbolji completed attempt za svaku instancu i spaja segmentne database-sweep indekse bez brisanja originalnih attempt foldera. Koristi ga kao jedini input za feature matrix:

```bash
cd ../master-regimes
make clustering-ready-audit LOGICAL_RUN_ID=pre-us-pilot FEATURE_TOPOLOGY=multi_region
```

Za EU+US GAC corpus koristi `FEATURE_TOPOLOGY=multi_region`, jer jedan GAC query ima N+1 plan evidence: GAC/main plan plus regionalne EU/US remote planove.

Za stvarni rerun ne pokreći preostale query-je pojedinačno. Prvo napravi segmentirani rerun plan:

```bash
make corpus-rerun-plan \
  CORPUS_EXECUTION_PLAN=../master-regimes/generated/corpus/pre-us-pilot/corpus_execution_plan.yml \
  CORPUS_LOGICAL_RUN_ID=pre-us-pilot \
  CORPUS_RERUN_PLAN_LABEL=rerun-01 \
  CORPUS_RERUN_HARD_TIMEOUT_SECONDS=1800
```

Ovaj korak čita `resolved_query_status.csv`, bira redove sa `needs_rerun=true`, i grupiše ih po segmentu: `dataset_id + runtime_config_id + target_group`. Generated rerun plan zato učita jedan dataset/runtime/target environment jednom, pa izvrši sve preostale query instance za taj segment. Time se izbjegava skupo zig-zag mijenjanje dataset profila i PostgreSQL/FDW postavki.

Ako je corpus manifest/source plan proširen nakon postojećeg logical runa, uključi i nove planirane instance koje još ne postoje u `resolved_query_status.csv`:

```bash
make corpus-rerun-plan \
  CORPUS_EXECUTION_PLAN=../master-regimes/generated/corpus/plan-c-pilot/corpus_execution_plan.yml \
  CORPUS_LOGICAL_RUN_ID=plan-c-bounded-pilot \
  CORPUS_RERUN_PLAN_LABEL=missing-plan-delta \
  CORPUS_RERUN_INCLUDE_MISSING_FROM_PLAN=true \
  CORPUS_RERUN_HARD_TIMEOUT_SECONDS=180
```

Ovo je namjerno eksplicitno da se novi veliki source plan ne pretvori slučajno u puni run. Rerun plan i dalje grupiše missing/timeout/failed instance po segmentu.

Ispisani `corpus_execution_plan.yml` zatim pokreni normalnim wrapperom:

```bash
make eu-us-gac-vps-corpus-run \
  CORPUS_EXECUTION_PLAN=<rerun-plan-dir>/corpus_execution_plan.yml \
  CORPUS_RUN_LABEL=pre-us-pilot-rerun-01 \
  CORPUS_LOGICAL_RUN_ID=pre-us-pilot \
  CORPUS_RERUN_OF=<prethodni-corpus-run-id>
```

Nakon database sweepa, u `../master-regimes` pokreni agent QA:

```bash
uv run python analysis/scripts/agent/run_all.py \
  --index-dir ../master-regimes-infra/generated/runs/database-sweeps/<sweep-id>/_index
```

Logički US region i `fdw_us` su aktivni za Plan C smoke i N+1/GAC provjere. `eu-us-gac-vps` zato treba čitati kao EU Citus + US Citus + GAC topologiju, ne kao EU-only GAC pripremu. U shared-VPC fazi EU/US nisu geografski razdvojeni; smoke output nije finalni WAN dokaz. Za WAN tvrdnje treba veći Plan C corpus uz eksplicitno kontrolisanu latenciju/network pressure.

Terminologija: `query-sweep` i `database-sweep` su ovdje execution backend nazivi za postojeće Make/runner korake. Eksperimentalni dizajn u novom `master-regimes` sloju treba se voditi kroz `corpus_id`, `corpus_cell_id`, `logical_question_id`, `execution_strategy`, `dataset_profile_id`, `runtime_config_id` i `intervention_role`, kako je definisano u `../master-regimes/docs/corpus-vocabulary.md`. Infra runner treba očuvati ta polja u manifestima i `_index` tabelama kada ih dobije iz corpus manifesta. Za runtime intervencije dodatno očuvava `runtime_intervention_axis`, `runtime_expected_effect`, `pg_options_json`, `psql_variables_json` i `fdw_server_options_json` u database-sweep `_index/runtime_sweeps.csv`. Za corpus-aware runove database-sweep `_index/corpus_cells.csv` je dimenzijska tabela, a `query_runs.csv` ostaje fact tabela pojedinačnih izvršenja.

## Query-bounded core kolekcija

Normalni workflow za ovaj rad skuplja samo artefakte koji ulaze u `core_v1` feature ugovor: SQL input, bindings, tekstualni `EXPLAIN`, `EXPLAIN ANALYZE` JSON, timing i run manifest. OS/network sampling i globalne `pg_stat`/Citus snapshot delte nisu dio normalnog query sweepa.

Hardware karakteristike node-ova se skupljaju kao globalni kontekst jednom na početku database sweepa, prije dataset/runtime/query loopova. To uključuje CPU, broj jezgara/threadova, memoriju, opcionalne RAM speed podatke kada ih host izloži, diskove i storage klasu (`nvme`, `ssd`, `virtual_ssd`, `virtual_disk_rotational_reported`, `hdd`, `unknown`). Ručno se može pokrenuti:

```bash
make eu-vps-single-hardware-snapshot HARDWARE_SNAPSHOT_LABEL=before-sweep-001
```

Static database/topology snapshot možeš snimiti odvojeno kada mijenjaš dataset, runtime konfiguraciju ili topologiju:

```bash
make eu-vps-single-sweep-static SWEEP_STATIC_LABEL=sweep-001
```

Zatim sekvencijalno izvršavaj query instance. Jedna query instanca se skuplja ovako:

```bash
make eu-vps-single-query-collect \
  QUERY_COLLECTION_LABEL=a1-lookback-30 \
  QUERY_COLLECTION_SQL_FILE=../psql-benchmarks/sql/stage_a/a1_rolling_aggregate.sql \
  QUERY_COLLECTION_VARS="lookback_days=30"
```

Ovaj workflow:

- u normalnom modu starta samo coordinator query-capture direktorij;
- izvršava tačno jedan `EXPLAIN (ANALYZE, BUFFERS, VERBOSE, FORMAT JSON)` na coordinatoru;
- prije toga snima i tekstualni `EXPLAIN (BUFFERS, VERBOSE)` bez `ANALYZE`, kao dodatni izvor keyword/signala koji se nekad ne vidi u JSON obliku;
- uključuje `citus.explain_all_tasks=on`, tako da plan sadrži sve Citus taskove;
- ne čuva query rezultate;
- zaustavlja capture odmah nakon završetka upita;
- fetchuje artefakte u `generated/runs/query-collections/<execution_id>/`.

Važna politika za statistike: PostgreSQL/Citus statistički pogledi (`pg_stat_*`, `pg_statio_*`, `pg_stat_statements`, `citus_stat_*`) su globalni ili kumulativni za node/database, pa se u normalnom sweepu ne skupljaju uz svaki pojedinačni query. OS/network counters također nisu primarni izvor za core pokazatelje. Ako ti treba debugging/profiling, uključi ga eksplicitno:

```bash
make eu-vps-single-query-collect \
  QUERY_COLLECTION_LABEL=a1-profile \
  QUERY_COLLECTION_DB_SNAPSHOTS=true \
  QUERY_COLLECTION_OS_SAMPLER=true
```

Taj run se tretira kao profiling/debug artefakt, ne kao osnovni `core_v1` feature set.

Ako lokalni `psql-benchmarks` ima izmjene koje nisu još pushane u GitHub, sinhronizuj ga na postojeće node-ove:

```bash
make repo-sync-psql-benchmarks
```

Za GAC topologiju koristi:

```bash
make eu-us-gac-vps-tools-sync
```

Execution backend petlja treba biti sekvencijalna: dataset config -> static snapshot -> parametarski set -> sve query instance jedna po jedna -> sljedeći parametarski set -> sljedeći dataset. Ipak, za režimske eksperimente ne treba mentalno polaziti od punog `dataset x runtime x query` proizvoda. Novi corpus sloj treba unaprijed odabrati koje ćelije imaju smisla, a backend ih može grupisati po dataset/runtime koracima radi efikasnosti.

Ako već imaš `instance_manifest.csv` iz `master-regimes render-workload`, možeš pokrenuti sekvencijalni smoke sweep:

```bash
make eu-vps-single-query-sweep \
  QUERY_SWEEP_LABEL=sweep-001-work-mem-4mb \
  QUERY_SWEEP_INSTANCE_MANIFEST=../master-regimes/generated/workloads/<suite-id>/<render-id>/instance_manifest.csv \
  QUERY_SWEEP_MAX_INSTANCES=2 \
  QUERY_SWEEP_GLOBAL_STATS_SCOPE=none
```

Za puni sweep povećaj ili ukloni limit tek kad smoke artefakti izgledaju dobro. Sam query sweep ne treba ručno analizirati kroz duboke foldere; poslije njega pokreni `master-regimes index-query-sweep` i koristi `_index/*.csv`.

Za dataset/config backend petlju koristi database sweep YAML. Minimalni primjer je:

```bash
make eu-vps-single-database-sweep \
  DATABASE_SWEEP_CONFIG=configs/sweeps/eu-vps-smoke.yml \
  DATABASE_SWEEP_LABEL=eu-vps-smoke
```

Format tog fajla je:

```yaml
datasets:
  - id: smoke
    profile: ../master-regimes/datasets/profiles/smoke.yml
    load_method: sql

runtime_configs:
  - id: wm4mb-fetch1000
    pg_options:
      work_mem: 4MB
    psql_variables:
      FETCH_COUNT: "1000"

workload:
  instance_manifest: ../master-regimes/generated/workloads/<suite-id>/<render-id>/instance_manifest.csv
  max_instances: 1

collection:
  global_stats_scope: none
```

Runner ide redom: snimi hardware snapshot jednom za cijeli database sweep, učitaj dataset profil preko `citus-datagen reset-and-load`, sekvencijalno izvrši SQL instance, pa zapiši normalizovani index. `work_mem` se primjenjuje kao session `PGOPTIONS`, a `FETCH_COUNT` kao psql varijabla; ne mijenja se globalni PostgreSQL config i ne pokreću se dva upita paralelno.

Nakon svakog dataset load-a runner sada snima capability audit u `dataset-loads/<load-id>/`:

- `dataset_counts.csv`
- `tenant_distribution.csv`
- `hot_tenant_manifest.csv`
- `tenant_worker_mapping.csv`
- `hot_tenant_worker_mapping.csv`
- `hot_tenant_worker_summary.csv`
- `shard_distribution.csv` ako je `citus_shards` dostupan
- `capability_audit.json`
- `dataset_parameter_values.json`

Ovo je dataset-level dokaz da `balanced`, `skew` ili `hot` profil stvarno ima deklarisane osobine. `dataset_parameter_values.json` je auditovani pool vrijednosti (`tenant_ids`, `hot_tenant_ids`, `cold_tenant_ids`, `dominant_hot_worker_probe_ids`) koji workload instance mogu koristiti bez ručnog pogađanja. Worker mapping artefakti odgovaraju na pitanje gdje su hot tenanti stvarno završili nakon Citus hash distribucije (`tenant_id -> shard_id -> worker`). Ne koristi se kao per-query statistički snapshot.

Ako je dataset već učitan i treba samo obnoviti audit/placement artefakte bez ponovnog load-a:

```bash
make single-eu-dataset-apply TOPOLOGY=eu-us-gac-vps \
  DATASET_PROFILE=../master-regimes/datasets/profiles/viewer-region-local-skew-balanced.yml \
  DATASET_REGION=eu \
  DATASET_AUDIT_ONLY=1
```

### Confirmatory skew capability smoke

Plan 10 koristi poseban bounded runner jer B i C moraju dijeliti isti dataset, a razlikovati se samo po determinističkom worker placementu hot shardova:

```bash
make confirmatory-skew-capability-smoke
```

Runner čisto učita zaključani mali dataset, uspostavi disperzovani B placement, izvrši dva SQL uslova, koncentriše hot shardove za C, ponovi ista dva uslova i zatim eksplicitnim inverznim move operacijama vrati B. U svakom stanju snima dataset i placement hashove. Raw artefakti idu u:

```text
generated/runs/confirmatory-skew-capability-smoke/<run-id>/
```

Komanda ne pokreće puni confirmatory corpus. Rezultat se zasebno provjerava lokalnim I0 reviewom iz `master-regimes`.

Svaki database sweep na kraju piše i normalizovani `_index/` folder. Primarni ulaz za parser/ML pipeline treba biti `_index/query_runs.csv`, ne ručno šetanje kroz `query-collections/**`. Detaljni artefakti ostaju u folderima, ali se do njih dolazi preko stabilnih kolona kao `query_run_id`, `query_sweep_id`, `dataset_id`/`dataset_profile_id`, `runtime_config_id`, `plan_json_file`, `explain_text_file` i opcijskih profiling kolona. Za nove corpus runove `_index` treba dodatno nositi `corpus_id`, `corpus_cell_id`, `logical_question_id`, `execution_strategy`, `intervention_role` i `expected_regime_targets`. Statični hardverski kontekst je u `_index/hardware_nodes.csv` i spaja se preko `database_sweep_id` + `node_name`.

`collection.global_stats_scope` može biti:

- `none`: default; preskoči globalne DB statistike i ostavi samo core EXPLAIN/timing/bindings artefakte.
- `sweep`: debug/profiling mod; globalne DB statistike se snime prije i poslije svih query instanci za taj dataset/runtime config.
- `query`: debug mod; globalne DB statistike se snime prije i poslije svake query instance.

### STATS-CEB vanjski portability adapter

STATS-CEB profil koristi poseban `external_relational_v1` adapter, ali ostaje unutar standardnog corpus/database-sweep toka. Ne koristi `citus-datagen` i ne pretpostavlja tenant/skew shemu.

Priprema na već podignutoj EU+US+GAC infrastrukturi:

```bash
make eu-us-gac-vps-stats-ceb-prepare
```

Komanda MD5-provjerava javni dump, obnavlja `app.stats` u oba regiona, obnavlja `analytics.stats_baseline`, importuje `stats_eu` i `stats_us` foreign schema te poredi osam zaključanih scalar-count upita. U result-validation artefaktima ostaju samo hash vrijednosti i statusi; database result redovi se ne čuvaju.

Za provjeru orchestration ugovora bez SQL izvršenja:

```bash
make stats-ceb-correctness-dry-run
```

Puni osam-query corpus se renderuje i pokreće iz `master-regimes` repozitorija preko `make stats-ceb-infra-dry-run` i, tek nakon pregleda prepare izlaza, `make stats-ceb-start`.

## Pravila

- Ne commitati `terraform.tfstate`, konkretne `*.tfvars`, privatne ključeve, certifikate ili provider credential-e.
- `ansible/group_vars/all.yml` se ne održava ručno u git-u. Generiše se ili se lokalno pravi iz `all.example.yml`.
- Tajne vrijednosti idu kroz environment varijable, Ansible Vault ili lokalni private config.
- Svaki veći eksperimentalni run treba zabilježiti hash sistemske konfiguracije.
