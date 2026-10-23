# Auditoria P0 do disco real

Executada em 22/10/2026, Windows 11 nativo (sem WSL), PowerShell 5.1 e Git Bash. Nenhum código legado foi executado. Bancos abertos somente com `mode=ro&immutable=1`. Nenhum SMTP, ATS, WordPress ou sync acionado.

## 1. Ambiente

| Item | Observado | Consequência |
|---|---|---|
| Raiz do workspace | `D:\dev\_dev web\_rvalle-site\__VAGAS` (pasta com espaço) | Scripts usam `-LiteralPath` e listas de argumentos |
| Raiz do engine | `D:\dev\_dev web\_rvalle-site\__VAGAS\_system` | Única pasta onde o engine grava |
| Git | Não há repositório em `__VAGAS` nem em `_rvalle-site` | Nenhum commit; `.gitignore` criado só como proteção futura |
| `python` no PATH | Resolve para o Python do **Inkscape** (`C:\Program Files\Inkscape\bin\python`) | Nunca usar `python` genérico; scripts usam `.venv\Scripts\python.exe` absoluto |
| Python real | 3.12 em `C:\Users\User\AppData\Local\Programs\Python\Python312` (`py -3.12`) | Base do `.venv` |
| Node | v24.16.0 (executa `.ts` com type stripping nativo) | Bridge TS possível, mas não necessário (ver REUSE-MAP) |
| Fuso do Windows | `E. South America Standard Time` (UTC-03:00) | Gatilhos 08/12/14/18 já em horário de Brasília |
| Porta 8765 | Ocupada por `python.exe` PID 10564, `rvalle-correios-tracker\...\server.py` (outro projeto) | Não encerrar; painel usa 8766 |
| Disco D: | fsync lento: 50 transações em journal DELETE levaram 78,8 s; 200 em WAL+`synchronous=NORMAL` levaram 0,03 s | Banco canônico obrigatoriamente em WAL+NORMAL; backups via `serialize()`/backup API com um único fsync |

## 2. Anexos e cópias extraídas (comparação por SHA-256)

| ZIP | Destino comparado | Resultado |
|---|---|---|
| `Artifact.zip` (ago/2026, prefixo `jobos/`) | `Artifact/` | 33 iguais, 9 divergentes (`jobs.db`, `run.py`, `sync.py`, `wordpress.py`, `rodar-ciclo.ps1`, `agendar-12h-18h.ps1`, workflow, `.gitignore`, `estrategias.json`). Disco é mais novo |
| `Artifact/jobos.zip` (21/10/2026) | `Artifact/` | 67 de 67 idênticos. É a versão extraída no disco |
| `web-vagas.zip` | raiz `__VAGAS` | 54 de 54 idênticos |
| `manifest.zip` (08/10/2026) | raiz `__VAGAS` | 26 iguais, 14 divergentes; versão antiga do portal. Não extrair por cima |
| `apollo-vagas_1.zip` | `apollo-vagas/` | 15 de 15 idênticos |

O blueprint cita `web-vagas(1).zip`, `jobs(1).json` e `rvalle.com.br-rafael(1).json`. No disco os nomes não têm `(1)`; os conteúdos foram usados como estão.

## 3. Banco legado `Artifact/jobs.db`

SHA-256 `554aef34f39aa06001f1782ecc7aeacc8e137fd612adda85962b810a3eaa680d`, 10.567.680 bytes, `integrity_check=ok`, `journal_mode=delete`. O `jobs.db-journal` (316 KB) tem cabeçalho zerado: não é journal quente.

| Métrica | Disco real | Anexo citado no blueprint |
|---|---:|---:|
| `jobs` | 2.022 | 1.118 |
| `events` | 4.200 (68 órfãos sem job) | 2.295 |
| `runs` | 1.316 | 251 |
| `applied` com `application_source='auto_sugerida'` | 13 | 13 |
| `applied` com origem nula | 15 | 15 |
| `closed=1` | 1.092 (1.091 com `removed_at`) | |
| `source_id` repetido em mais de uma linha | 123 grupos | |
| URL repetida | 79 grupos | |

Procedência das 28 "candidaturas":

- 15 com origem nula têm evento `applied` "marcado manualmente a pedido do usuario (aplicado em 24/08/2026)". É indício de ação do usuário, não prova de plataforma.
- 13 `auto_sugerida` vêm de `consolidar_pendentes()`; há 84 eventos "consolidada como candidatura" para elas (consolidações e desfazimentos repetidos quando o e-mail falhava).
- Os dois grupos vão para `legacy_needs_review` e ficam fora do total comprovado.

Datas: `date_posted` tem 1.582 ISO de dia, 230 `~AAAA-MM-DD` (detecção estimada), 180 vazias, 29 relativas ("Posted Today", "Posted 3 Days Ago") e 1 texto livre. `interview_prob` preenchido em 1.979 linhas (não será exibido).

Nomes de empresa duplicados por grafia: `PRIO/prio`, `MODEC/modec-br`, `NORSUL/norsul`, `Brava Energia/bravaenergia`. Fontes: `web:greenhouse` 1.306 (todas Capco, quadro global), `workday` 183, `gupy` 176, `web:inhire` 114, `web:webflow_dof` 97, `web:j2w` 85, `totvs` 57, `web:workday` 4.

`out/dry.db` é banco de teste com 5 vagas; não é importado.

## 4. Snapshot do portal `jobs.json`

SHA-256 `a8f1034c3604ceb5...`, `updatedAt 2026-10-08T04:20:18Z`, 28 empresas, 252 vagas abertas, nenhuma "Finalizado". `assets/jobs-data.js` é a mesma informação como `window.JOBOS_BOOK`. IDs: Gupy numérico (mesmo ID global usado pelo legado Python), SuccessFactors caminho `/job/<slug>/<id>/`, Workday `externalPath`, inHire UUID, DOF slug, TOTVS número de página, Greenhouse ID.

## 5. Perfil `rvalle.com.br-rafael.json`

SHA-256 `baccac260f06a178...`, 222.830 bytes, **31** módulos de topo (o blueprint citava 32). Contém `truth_boundaries`, `software_systems_tree` com status (`strong/proven`, `used/proven`, `developing`, `personal-project`, `do-not-claim`), `education_tree.edu_civil`, certificados com `current_safe_wording: "realizado; reciclagem pendente"`, `mobility_and_preferences` com CLT/PJ e pretensão `UNKNOWN_NOT_DOCUMENTED`. É a autoridade inicial de fatos; `config/profile.yml` legado é política antiga.

## 6. Código e riscos verificados

Confirmados no código (arquivo:linha nos relatórios de leitura):

- A01: `autoapply.consolidar_pendentes()` (110-162) é chamada por `run.py boletim` (483) e portanto pelo `ciclo`.
- A02: `store.job_id()` (97-101) usa hash de empresa+título+local truncado.
- A03: `store.upsert()` (184-187) só grava descrição se a anterior estava vazia.
- A04: `store.mark_closed()` (214-228) fecha por `last_seen` com 2 dias.
- A05: `store.upsert()` (200) grava `~AAAA-MM-DD` em `date_posted`.
- A06/A07/A08: `score.py`, `triage.py` e `compat.py` aplicam políticas diferentes; `interview_probability` com penalidade de 0,75 por gap; `compat.py:211` corta descrição em 2.500 caracteres, `triage.py:613` em 1.500.
- A12: `run.py` usa `sys.argv` cru; flags desconhecidas são ignoradas; `ciclo` engole falhas de etapas e sai 0.
- A13: `rodar-diario.ps1` usa `python` do PATH e embute endereço real; `rodar-ciclo.ps1` lê `segredos.ps1` (ausente no disco).
- A14/A15/A16: `merge-jobs.ts` fecha vaga ausente na primeira leitura não vazia; `rio.ts` bloqueia Macaé, Vitória, Santos e outras; `host.ts` escuta em `0.0.0.0:8080`.
- A17: `jobos.js` guarda Aplicadas/Ocultas/Promovidas em `localStorage` (`jobos-saved`, `jobos-muted`, `jobos-lifted`).
- Plugin WP: `completo` do arquivo é ignorado; sync assume completo quando há `empresas`, podendo encerrar vagas por exportação parcial.

## 7. Agendamentos existentes

| Tarefa | Ação | Situação |
|---|---|---|
| `jobos-vagas - ciclo 12h` | `powershell -File "D:\dev\_rafael.rvalle.com.br\jobos mapping offers\jobos\windows\rodar-ciclo.ps1"` | Caminho **não existe**; último resultado 0xFFFD0000 (22/10 12:00) |
| `jobos-vagas - ciclo 18h` | mesmo script | Último resultado 0xC000013A (21/10 18:00) |
| `RVALLE-Correios-Jobos-1530` | `force-track-jobos.bat` do plugin de Correios | Outro projeto. Não tocar |

O log `Artifact/windows/ultima-execucao.log` registra ciclos 12/18h de 12 a 18/10 e 0 e-mails enviados.

## 8. Publicação e exposição

`__VAGAS` contém site estático (`index.html`, `assets/`, `sw.js`). Não há evidência de RealTimeSync configurado nesta pasta, mas o plugin cita RealTimeSync para `D:\dev\_dev.rvalle.com.br`. `.claude/launch.json` define `python -m http.server 8765` na raiz `__VAGAS`, o que serviria `rvalle.com.br-rafael.json`, `Artifact/jobs.db` e `_system/` inteiros. O engine novo nunca serve a raiz; ver DEC-009.
