# Cobertura das fontes

Gerado por `jobos sources --markdown` a partir de `status.source_health`. Não edite à mão.
Falha ou leitura parcial nunca encerra vaga.

As colunas históricas do P0 (config snapshot, Python legado, TS) ficam no histórico do git.
Medição de 30/10/2026: o "ok" de aker-smart, airswift-smart e trident-workable é a leitura de 29/10 do leitor anterior. O próximo ciclo real usa aker_site_json, airswift_hubspot, sage_frecruit e oracle_ce (DEC-023) e ainda não coletou esses quadros. ABS aparece como never_run nesse leitor.

| source_id | empresa | plataforma | leitor | ligado | saúde | última leitura | ativas |
|---|---|---|---|---|---|---|---|
| prio-gupy | PRIO | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:18+00:00 | 9 |
| modec-gupy | MODEC | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:18+00:00 | 8 |
| norsul-gupy | Norsul | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:18+00:00 | 7 |
| brava-gupy | Brava Energia | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:22+00:00 | 30 |
| wilsonsons-gupy | Wilson Sons | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:21+00:00 | 51 |
| ocyan-gupy | Ocyan | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:23+00:00 | 17 |
| qualidados-gupy | Qualidados | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:21+00:00 | 40 |
| oceanica-gupy | Oceânica | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:26+00:00 | 43 |
| vinci-gupy | VINCI Energies | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:28+00:00 | 66 |
| nexa-gupy | Nexa Tecnologia | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:26+00:00 | 4 |
| enauta-gupy | Enauta / 3R | gupy | gupy_tenant | não | no_reader | 2026-10-22T23:52:13+00:00 | 0 |
| minsait-gupy | Minsait | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:31+00:00 | 2 |
| vibra-gupy | Vibra Energia | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:29+00:00 | 50 |
| subsea7-sf | Subsea7 | successfactors_j2w | j2w_search | sim | ok | 2026-10-29T17:00:37+00:00 | 25 |
| sbm-sf | SBM Offshore | successfactors_j2w | j2w_search | sim | ok | 2026-10-29T17:00:31+00:00 | 12 |
| yinson-sf | Yinson | successfactors_j2w | j2w_search | sim | ok | 2026-10-29T17:00:34+00:00 | 4 |
| halliburton-sf | Halliburton | successfactors_j2w | j2w_search | sim | ok | 2026-10-29T17:00:38+00:00 | 30 |
| transocean-workday | Transocean | workday | workday_cxs | sim | ok | 2026-10-29T17:00:32+00:00 | 1 |
| equinor-workday | Equinor | workday | workday_cxs | sim | ok | 2026-10-29T17:00:34+00:00 | 0 |
| shell-workday | Shell | workday | workday_cxs | sim | ok | 2026-10-29T17:00:36+00:00 | 0 |
| baker-workday | Baker Hughes | workday | workday_cxs | sim | ok | 2026-10-29T17:00:37+00:00 | 24 |
| technipfmc-workday | TechnipFMC | successfactors_j2w | j2w_search | sim | ok | 2026-10-29T17:00:40+00:00 | 6 |
| aker-smart | Aker Solutions | successfactors | aker_site_json | sim | ok | 2026-10-29T17:00:39+00:00 | 0 |
| airswift-smart | Airswift | hubspot | airswift_hubspot | sim | ok | 2026-10-29T17:00:39+00:00 | 0 |
| oceanpact-inhire | OceanPact | inhire | inhire | sim | ok | 2026-10-29T17:00:39+00:00 | 66 |
| dof-workable | DOF | workable | workable | sim | ok | 2026-10-29T17:00:41+00:00 | 96 |
| dof-webflow | DOF | webflow | dof_webflow | não | no_reader | 2026-10-22T23:52:32+00:00 | 0 |
| bram-totvs | Bram Offshore | totvs | totvs | sim | ok | 2026-10-29T17:00:41+00:00 | 29 |
| capco-greenhouse | Capco | greenhouse | greenhouse | sim | ok | 2026-10-29T17:00:43+00:00 | 129 |
| trident-workable | Trident Energy | sage_frecruit | sage_frecruit | sim | ok | 2026-10-29T17:00:41+00:00 | 0 |
| sapura-vagas | Sapura (Seagems) | vagas_com_br | vagas_com_br | sim | ok | 2026-10-29T17:00:42+00:00 | 0 |
| abs-oracle | ABS | oracle_ce | oracle_ce | sim | never_run | 2026-10-29T17:00:41+00:00 | 0 |
| constellation-gupy | Constellation Oil Services | gupy | — | sim | no_reader | 2026-10-29T17:00:41+00:00 | 0 |
| petrobras-concursos | Petrobras | concurso | — | sim | no_reader | 2026-10-29T17:00:41+00:00 | 0 |
| bwoffshore | BW Offshore | unknown | — | sim | no_reader | 2026-10-29T17:00:41+00:00 | 0 |
| altera-gupy | Altera&Ocyan | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:44+00:00 | 2 |
| perbras-gupy | Perbras | gupy | gupy_tenant | sim | ok | 2026-10-29T17:00:45+00:00 | 16 |
| totalenergies | TotalEnergies | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| saipem | Saipem | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| slb | SLB | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| karoon | Karoon Energy | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| perenco | Perenco | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| brunel | Brunel Brasil | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| nesfircroft | NES Fircroft | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| petroplan | Petroplan | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| oriongroup | Orion Group | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| michaelpage | Michael Page Brasil | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| hays | Hays Brasil | unknown | — | sim | no_reader | 2026-10-29T17:00:42+00:00 | 0 |
| gupy-portal-queries | Portal Gupy (consultas) | gupy_portal | gupy_portal_search | não | no_reader | never_run | 0 |
