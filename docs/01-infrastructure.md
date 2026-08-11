# Reprodukcija infrastrukture

## Topologija

Aktivni N2 infrastrukturni profil kreira sedam PostgreSQL čvorova:

| Logička uloga                  | Broj |
| ------------------------------ | ---: |
| EU Citus coordinator           |    1 |
| EU Citus worker                |    2 |
| US Citus coordinator           |    1 |
| US Citus worker                |    2 |
| Globalni analitički čvor (GAC) |    1 |

U kuriranom profilu EU i US su logički regioni u istom Vultr `ams` regionu. Kontrolisana WAN latencija, jitter i loss uvode se pomoću `tc netem`; geografska udaljenost providera nije skriveni eksperimentalni faktor.

N3 profil dodaje APAC coordinator i dva APAC workera, pa ukupno ima deset čvorova. APAC je također logička uloga u `ams` i priključuje se postojećem VPC-u. Stariji `clean-run-v1` je izuzetak: njegovi EU, US i GAC čvorovi bili su u `ams`, `ewr` i `cdg`. Te dvije fizičke topologije ne treba objedinjavati u jednu tvrdnju.

Aktivni jeftini profil koristi `vhf-1c-2gb`. U konfiguraciji je zabilježen i ranije korišten `vbm-6c-32gb` profil. Promjena se radi na jednom mjestu:

```text
sources/master-regimes-infra/configs/systems/eu-us-gac-vps.yml
```

## Preduslovi

Preporučeno okruženje je Linux ili WSL2 sa:

- Python 3.12;
- `uv`;
- Terraform 1.5 ili noviji;
- Ansible;
- OpenSSH klijentom;
- `make`, `rsync` i standardnim GNU alatima;
- Vultr nalogom sa dovoljnim limitom instanci.

Lokalne tajne se čuvaju u:

```text
~/.config/master-regimes-infra/env
```

Minimalno su potrebne varijable:

```bash
VULTR_API_KEY=...
MASTER_REGIMES_SSH_PUBLIC_KEY='ssh-ed25519 ...'
MASTER_REGIMES_SSH_PRIVATE_KEY_FILE="$HOME/.ssh/id_ed25519"
MASTER_REGIMES_ADMIN_IPV4_CIDRS='["203.0.113.10/32"]'
MASTER_REGIMES_WEB_IPV4_CIDRS='["203.0.113.10/32"]'
MASTER_REGIMES_DATABASE_CLIENT_IPV4_CIDRS='["203.0.113.10/32"]'
MASTER_REGIMES_GAC_PUBLIC_ACCESS_CIDRS='["203.0.113.10/32"]'
MASTER_REGIMES_POSTGRES_ADMIN_PASSWORD='...'
MASTER_REGIMES_APP_DB_PASSWORD='...'
MASTER_REGIMES_ANALYTICS_DB_PASSWORD='...'
```

Ne kopirati stvarne vrijednosti u repozitorij. Tačan ugovor konfiguracije je u `configs/systems/eu-us-gac-vps.yml`.

## Podizanje

Iz korijena ovog repozitorija:

```bash
make infra-env
make infra-plan  # trenutno planira samo EU anchor
make infra-up    # renderuje i primjenjuje puni N2 lifecycle
make infra-ping
```

Postojeći `infra-plan` nije neprimjenjujući plan cijelog N2 grafa. US plan se formira unutar shared-VPC `infra-up` skripte, a N3 APAC extension također zahtijeva postojeće N2 stanje i zatim primjenjuje plan. Prije troškovnog live reruna potrebno je pregledati lifecycle skripte; paket trenutno nema jednu plan-only komandu za kompletan N2 ili N3 graf.

`infra-up` renderuje Terraform/Ansible konfiguraciju, kreira VPS/VPC resurse, instalira PostgreSQL 18 i Citus 14, formira oba Citus klastera, postavlja GAC i sinhronizuje alate. Paket čuva tačne source snapshot commitove u `config/release-spec.json`, ali live Ansible konfiguracija još koristi granu za `citus-datagen`; prije reruna treba eksplicitno checkoutovati objavljeni commit. Terraform lock datoteke čuvaju Vultr provider `2.31.2` za EU/US i `2.32.0` za APAC. Verzija Ansible corea, `ansible.posix` i tačni apt buildovi nisu potpuno zaključani.

## Gasenje

```bash
make infra-down
```

Prije gašenja treba završiti kopiranje run artefakata. Terraform state i credential-i ostaju lokalni i namjerno nisu dio release paketa.

## Istorijski hardver

Glavni `clean-run-v1` izvršen je na čvorovima sa 8 logičkih CPU-a i približno 16 GiB RAM-a. Kasniji companion i repeatability runovi koristili su čvorove sa 1 CPU i približno 2 GiB RAM-a. Hardver nije sistematski sweepovan.

Tačne izmjerene specifikacije po čvoru i provenance konfiguracije nalaze se u:

```text
artifacts/results/experimental-reproducibility-v2/infrastructure.csv
```

Zbog toga trenutni jeftini profil reprodukuje topologiju i postupak, ali ne obećava identično apsolutno vrijeme historijskih runova.
