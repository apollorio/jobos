# Cobertura de fontes (P0)

Cadastro canônico gerado em `config/sources.yaml` a partir de `jobs.json` (28 empresas) e `Artifact/config/companies.yml` (extras). Leitor principal único por fonte. "Python legado" = função em `Artifact/jobos/sources`; "TS" = `assets/load-jobs.ts`. Smoke test real fica registrado em `docs/PROGRESS.md`; esta tabela não prova funcionamento atual.

| source_id | Empresa | Plataforma | Config (snapshot) | Python legado | TS | Adapter escolhido | Escopo |
|---|---|---|---|---|---|---|---|
| prio-gupy | PRIO | Gupy | prio.gupy.io | list_tenant | gupy | gupy_tenant | full_board |
| modec-gupy | MODEC | Gupy | modec-br.gupy.io | list_tenant | gupy | gupy_tenant | full_board |
| norsul-gupy | Norsul | Gupy | norsul.gupy.io | list_tenant | gupy | gupy_tenant | full_board |
| brava-gupy | Brava Energia | Gupy | bravaenergia.gupy.io | list_tenant | gupy | gupy_tenant | full_board |
| wilsonsons-gupy | Wilson Sons | Gupy | wilsonsons.gupy.io | sem entrada | gupy | gupy_tenant | full_board |
| ocyan-gupy | Ocyan | Gupy | ocyan.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| qualidados-gupy | Qualidados | Gupy | qualidados.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| oceanica-gupy | Oceânica | Gupy | sejaoceanica.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| vinci-gupy | VINCI Energies | Gupy | vinci-energies.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| nexa-gupy | Nexa Tecnologia | Gupy | nexatecnologia.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| enauta-gupy | Enauta / 3R (Brava) | Gupy | 3rpetroleum.gupy.io | sem leitor | gupy | gupy_tenant | full_board |
| minsait-gupy | Minsait | Gupy | minsait.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| vibra-gupy | Vibra Energia | Gupy | vibraenergia.gupy.io | só portal agregado | gupy | gupy_tenant | full_board |
| subsea7-sf | Subsea7 | SuccessFactors J2W | careers.subsea7.com | j2w busca/sitemap | sf | j2w_search | filtered_board (Rio de Janeiro) |
| sbm-sf | SBM Offshore | SuccessFactors J2W | careers.sbmoffshore.com | j2w | sf | j2w_search | filtered_board |
| yinson-sf | Yinson | SuccessFactors J2W | careers.yinson.com | j2w | sf | j2w_search | filtered_board |
| halliburton-sf | Halliburton | SuccessFactors J2W | jobs.halliburton.com | sem leitor | sf | j2w_search | filtered_board |
| transocean-workday | Transocean | Workday CXS | deepwater/wd1/BrazilExternalCareerSite | workday | workday | workday_cxs | full_board |
| equinor-workday | Equinor | Workday CXS | equinor/wd3/EQNR | workday | workday | workday_cxs | filtered_board (searchText "Brazil") |
| shell-workday | Shell | Workday CXS | shell/wd3/ShellCareers | workday | workday | workday_cxs | filtered_board (searchText "Rio de Janeiro") |
| baker-workday | Baker Hughes | Workday CXS | bakerhughes/wd5/BakerHughes | workday | workday | workday_cxs | filtered_board (searchText "Brazil") |
| technipfmc-workday | TechnipFMC | Workday CXS | technipfmc/wd1/TechnipFMC (não verificado; legado com erro) | workday | não | workday_cxs | filtered_board (searchText "Brazil") |
| aker-smart | Aker Solutions | SmartRecruiters | akersolutions | genérico | smart | smartrecruiters | filtered_board (country=br) |
| airswift-smart | Airswift | SmartRecruiters | airswift | genérico | smart | smartrecruiters | filtered_board (country=br) |
| oceanpact-inhire | OceanPact | inHire | tenant oceanpact | inhire | inhire | inhire | full_board |
| abs-oracle | ABS | Oracle CE | hbbq.fa.us2 / CX_1 | não | oracle | sem adapter (unconfigured) | |
| dof-webflow | DOF | Webflow | dof.com/vacancies | webflow_dof | dof | dof_webflow | full_board |
| bram-totvs | Bram Offshore | TOTVS | bramoffshore | totvs | bram | totvs | full_board |
| capco-greenhouse | Capco | Greenhouse | board capco, escritório 114971 | greenhouse (quadro global) | greenhouse (escritório) | greenhouse | filtered_board (office 114971) |
| trident-workable | Trident Energy | Workable | trident-energy | workable | não | workable | full_board |
| sapura-vagas | Sapura (Seagems) | vagas.com.br | seagems | vagas_com_br | não | vagas_com_br | full_board |
| constellation-gupy | Constellation | Gupy | tenant desconhecido | portal | não | sem adapter (unconfigured) | |
| petrobras-concursos | Petrobras | Concurso público | edital | special | não | sem adapter (unconfigured) | |

Empresas listadas no YAML legado sem leitor e sem configuração verificável (BW Offshore, Altera, TotalEnergies, Saipem, SLB, Karoon, Perenco, Brunel, NES Fircroft, Petroplan, Orion, Michael Page, Hays) entram no cadastro como `unconfigured`, para aparecerem no painel sem fingir coleta.

Fonte agregada `gupy-portal-queries` (16 consultas do `queries.yml`) entra desativada: é `incremental_query`, nunca autoriza encerramento, e gerou ruído de empresas fora da lista (por exemplo, colchões, estágio). Adzuna fica fora (exige credencial própria).

Empresas excluídas por decisão do usuário em 24/08/2026 (dragagem: Boskalis, DEME, Royal IHC, Jan De Nul, Van Oord) continuam fora do cadastro; a exclusão fica visível em `config/preferences.yaml`.

## Smoke test real (22/10/2026 ~20:36 Brasília, `cycle --dry-run --no-notify`, banco temporário)

Leitura pública sem login, limites padrão (timeout 25 s, 3 tentativas, até 15 páginas e 25 detalhes por fonte). Prova somente aquele fluxo naquele momento.

| Fonte | Status | Vagas | Observação |
|---|---|---:|---|
| prio, modec, norsul, brava, wilsonsons, ocyan, qualidados, oceanica, vinci, nexa, minsait, vibra (Gupy) | complete | 8/8/5/25/54/15/37/40/54/2/19/45 | listagem OK; detalhe pelo portal antigo deu 404 em todas, corrigido para a página da vaga (`__NEXT_DATA__.job`) |
| enauta-gupy | complete | 0 | tenant 3R vazio (fusão com Brava) |
| subsea7-sf / sbm-sf / yinson-sf / halliburton-sf | complete | 21 / 8 / 4 / 31 | paginação J2W até o fim; detalhes lidos |
| transocean / baker / shell (Workday) | complete | 2 / 26 / 1 | baker atingiu limite de 25 detalhes (restante no próximo ciclo) |
| equinor-workday | complete | 0 | busca "Brazil" vazia (snapshot de 08/10 também 0) |
| technipfmc-workday | **failed** | 0 | HTTP 422: site/tenant do YAML legado inválido (legado também falhava) |
| aker-smart / airswift-smart | complete | 0 / 0 | filtro country=br vazio |
| oceanpact-inhire | complete | 72 | |
| dof-webflow | complete | 100 | quadro global; 4 avisos de detalhe sem bloco rich-text |
| bram-totvs | complete | 31 | |
| capco-greenhouse | complete | 1 | escritório 114971 (Rio) |
| trident-workable / sapura-vagas | complete | 0 / 0 | contas existentes sem vagas (igual ao legado) |
| 16 fontes sem leitor | unconfigured | | aparecem no painel como "sem leitor" |
