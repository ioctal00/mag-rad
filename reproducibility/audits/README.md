# Offline audit ponovljivosti

Ovaj direktorij sadrži pet nezavisnih validatora i jedan konsolidovani nalaz. Nijedan validator ne pristupa cloud provideru, hostovima ili bazi podataka.

| Oblast | Validator | Provjerava |
| --- | --- | --- |
| Terraform | `terraform/audit.py` | N2/N3 graf, fizičku lokaciju, VPC odnos, verzije i historijski provenance |
| Ansible | `ansible/audit.py` | playbookove, uloge, pinove, dataset/FDW bootstrap i rollback granice |
| Dataset | `datasets/audit.py` | profile, hashove, stvarni eksperimentalni obuhvat, regionalnu neravnotezu i skew |
| Sweep | `sweeps/audit.py` | renderovanje, ponavljanja, redoslijed, slotove, nastavak i zbirne brojeve |
| Collector | `collector/audit.py` | GAC, regionalne i worker/task veze, pokušaje, result hashove i host telemetriju |

Pokretanje svih provjera:

```bash
make reproducibility-audit
```

Potpuna provjera svih release checksumova:

```bash
make reproducibility-audit-full
```

Status `PASS_WITH_DOCUMENTED_LIMITATIONS` znači da nema strukturne kontradikcije u zapakovanom dokazu, ali da bit-identičan live replay nije garantovan. Poznate granice, poput nepostojanja database dumpa, historijskog Terraform plana ili query-level OS atribucije, ostaju vidljive u nalazu i ne pretvaraju se u prolaznu tvrdnju.

`summary.json` je mašinski čitljiv sažetak, a `REPRODUCIBILITY_AUDIT.md` njegov čitljivi prikaz. Puni nalazi i lokalne komande nalaze se u poddirektorijima oblasti.
