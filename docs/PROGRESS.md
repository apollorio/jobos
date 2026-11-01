# Progresso real do JOBOS

Atualizado em: 30/10/2026
Ambiente: Windows 11 nativo; Python 3.12.10 em `_system\.venv` (lock em `requirements.lock`); Node 24 para `node --check` do painel e para compilar `web/painel/src/preparo.ts` com o esbuild 0.25.10 de `__core.js`
Raiz confirmada: `D:\dev\_dev web\_rvalle-site\__VAGAS\_system`
Fase atual: P0 a P5 implementados e verificados; ondas W0/W1 do `docs/EXECUTION-PLAN-2026-10-23.md` concluídas (24/10); kit de CV local (P3.1-R) substitui o bloqueio do CV Builder para o caminho principal. Em 30/10 entrou o laço manual (currículo no painel, comprovante, pendências, frescor) e o registro dos leitores reais de Aker, Airswift, Trident e ABS (DEC-023). Automação de navegador não começou: a DEC-022 não foi aceita.
Última entrega verificável: o painel abre como aplicativo local por `JOBOS.cmd` (janela `--app`). Porta do painel: 8776, porque a 8766 está com o WhatsApp Hub.

## Concluído

- [x] P0: auditoria (`AUDIT.md`, `SOURCE-COVERAGE.md`, `REUSE-MAP.md`, `CONFLICTS.md`, `DECISIONS.md`); backup P0 em `data/backups/p0-20261022T151356Z/`
- [x] P1: pacote `src/jobos`, CLI estrita, migração v1, importação idempotente (SQLite legado + `jobs.json`), perfil versionado, 28 candidaturas legadas em revisão
- [x] P2: 11 adapters (`SourceBatch` com status/completude/escopo), persistência com versões, ausência protegida (2 leituras completas + 6 h + mesmo escopo + guarda de queda anômala), baseline sem alerta, relações de possível republicação
- [x] P3: API FastAPI em 127.0.0.1:8766 (Host/Origin/X-JOBOS, allowlist estática), fila `work_items` com lease e worker, portal antigo servido sem edição com `jobs.json`/`jobs-data.js` gerados do SQLite, painel operacional `/painel/` (8 seções). A porta operacional do painel é 8776 (DEC-020); a 8766 ficou com o WhatsApp Hub.
- [x] P4: análise determinística por requisito (atendido/parcial/lacuna/desconhecido) com JSON Pointer, cobertura, nota só com cobertura ≥ 60%, função pelo `role_fit_tree`, preferências visíveis, prioridade separada; política `matching-v7` desde 27/10 (W2a: HTML e instruções do anúncio não viram requisito, DEC-021). W2a foi só essa sanitização. A calibração com rótulos continua pendente.
- [x] Execução real pelo Agendador do Windows verificada (código 2 = parcial pela TechnipFMC em 23–24/10). Esse código 2 está resolvido. O buraco aberto é cobertura de horário: o notebook dorme e WakeToRun está desligado.
- [x] P5: outbox persistente (rascunho/preview .txt/.html/.eml), transporte SMTP separado e desligado, estados accepted/unknown/failed_transient, scripts Windows, tarefa `JOBOS Local Engine` registrada (08/12/14/18 h)
- [x] Aplicativo local: `JOBOS.cmd` sobe o servidor se precisar e abre `/painel/` em janela de aplicativo (Edge ou Chrome `--app`). Se `/api/health` já responder `jobos-local`, só abre a janela. O manifesto fica em `/painel/manifest.webmanifest`, com `scope` e `start_url` em `/painel/`. Duplo clique no `index.html` do disco não é o aplicativo. `preparo.ts` continua fora da allowlist.
- [x] Preparo por vaga no detalhe: `src/jobos/matching/prepare.py` seleciona, na leitura, textos já escritos no perfil (requisito atendido ou parcial, wording seguro, história, headline). Headline automático só quando um cobre mais domínios do que o seguinte. A página em TypeScript está em `web/painel/src/preparo.ts` e o navegador recebe `web/painel/preparo.js`. Não grava CV, não marca envio e não chama IA. A política `matching-v6` permanece.

## Arquivos principais

`src/jobos/` (cli, pipeline, persistence, collectors/*, matching/*, notifications/*, api/*, legacy/*, storage/*), `config/*.yaml`, `config/profile/master.json` (cópia do perfil), `web/painel/*` (fonte `src/preparo.ts`, saída `preparo.js`), `scripts/build-preparo.mjs`, `scripts/windows/*.ps1`, `tests/*` (406 testes em 30/10/2026; as contagens anteriores permanecem na tabela), `docs/*`, `README.md`, `CLAUDE.md`.

## Verificações

| Comando/teste | Resultado real | O que verifica | Limite |
|---|---|---|---|
| `pytest -p no:cacheprovider tests` | **126 passed** (25 s) em 22/10 | T01-T04, T06-T18, T20-T27, T31-T37, T40-T45, adapters offline | sem rede |
| `pytest -p no:cacheprovider tests` | **141 passed** (37 s) em 23/10 | suíte atual, com `tests/test_prepare.py` e o campo `support` no detalhe | sem rede |
| `pytest -p no:cacheprovider tests` | **322 passed** (exit 0), medição de 23-24/10 | suíte atual | não repetida na W0 |
| W1 (24/10, worktree `w0-w1`): `pytest -p no:cacheprovider tests` | **387 passed, 1 xfailed** (exit 0) | +T25, T38, T42, T43, saídas 4/5, `fuso_windows`, log diário (W1a); matriz de saúde das fontes (W1b, 14 testes); kit de CV T28/T29/T47 + `cv build` (W1c, 19 testes) | xfail estrito: extrator de requisitos aceita HTML/instruções após "Requisitos:" (W2) |
| W2a (27/10, worktree `w2a-requirements-sanitize`): `pytest -p no:cacheprovider tests` | **389 passed, 0 xfail** (exit 0) | T42 sem xfail: anúncio com `<script>`, `<img onerror>` e instrução ao avaliador tem os mesmos requisitos, decisão, nota e cobertura do anúncio limpo; `test_html_and_agent_instructions_are_not_requirements`; `matching-v7` (DEC-021) | consulta somente leitura no banco real: 0 de 3.701 descrições com HTML ou instrução |
| W2a: `cycle --dry-run --fixtures` | exit 2 (parcial esperado), banco temporário, `policy_version` `matching-v7`; mesmos estados de fonte e decisões (good_fit 1, insufficient_data 2) que o `main` em `matching-v6` | dry run isolado após a mudança de política | a worktree não tem `data/`, então o banco temporário começa vazio (novas em vez de alteradas) |
| W1: `node --check web/painel/painel.js`; `cycle --dry-run --fixtures`; `doctor` | exit 0; exit 2 (parcial esperado, banco temporário); `fuso_windows` OK (UTC-03:00 = Brasília) | painel compila; dry run isolado | |
| W1: painel `/painel/#fontes` servido da worktree com cópia do backup pre-w1 (porta 8793) | matriz renderiza 49 fontes: 1 falha, 18 sem leitor, 30 ok; filtros e ordenação | UI da saúde das fontes com dados reais | cópia anterior à correção TechnipFMC |
| W1b: `collect --source technipfmc-workday --dry-run` | complete, 8 vagas | nova configuração `j2w_search` | `max_details: 0` no teste; detalhe por vaga não exercitado |
| `tsc` estrito em `web/painel/src/tsconfig.json`, `node scripts/build-preparo.mjs`, `node --check` de `preparo.js` e `painel.js` | exit 0 | o navegador carrega o JavaScript compilado; a fonte editável é TypeScript | sem clique no navegador |
| `pytest -p no:cacheprovider tests/test_api.py tests/test_prepare.py` | **26 passed** (125 s) em 23/10 | manifesto do painel, ícones PNG, `preparo.ts` recusado, preparo sem envio | sem rede; suíte completa não foi repetida nesta etapa |
| Parser do `start-dashboard.ps1` e `node --check` de `painel.js` | exit 0 | o lançador e o aviso de `file:` compilam | a janela `--app` depende do Edge ou do Chrome instalados |
| Servidor destacado na 8776 e janela `--app` | `/api/health` 200 `jobos-local`; `/painel/` traz `manifest.webmanifest` e `preparo.js`; manifesto com `scope` `/painel/` e `display` standalone | o duplo clique tem um processo que continua depois do lançador | a 8766 seguiu com o WhatsApp Hub; esse processo não foi encerrado. As seções do painel não foram clicadas uma a uma |
| SHA-256 de `config/profile/master.json` e de `https://rvalle.com.br/rafael.json` | iguais, 222830 bytes, versão `2026-10-21.100`, prefixo `baccac260f06a178` | a cópia local e o JSON público são o mesmo arquivo neste momento | a autoridade da análise continua o arquivo local |
| `import-legacy --apply` 2x | imported → already_imported | idempotência real | |
| `cycle --dry-run --fixtures` | partial (exit 2); hash do banco real idêntico antes/depois; nenhum preview real | T31, fixture rotulada | |
| `cycle --fixtures` sem `--dry-run` | exit 3 | fixture nunca no banco real | |
| `cycle --dry-run --no-notify` (rede) | 29 complete, 1 failed (TechnipFMC HTTP 422) | smoke de todas as plataformas | só aquele momento |
| `cycle --mode manual` (real) | partial exit 2, 4m21s; 294 novas (baseline, sem alerta), 184 ausentes não confirmadas, 0 encerradas | primeira coleta real | |
| `backup --label pre-w1` (live, 24/10 ~11:39 Brasília) | `Backup: D:\dev\_dev web\_rvalle-site\__VAGAS\_system\data\backups\20261024T143940-pre-w1`; integridade=ok; restauração verificada=sim | cópia SQLite online antes da W1 | backup do banco; pastas do portal não incluídas |
| `jobos status` e `jobos doctor` (live, 24/10 ~11:40 Brasília) | status: candidaturas `legacy_needs_review` 13 e `submitted_manual` 15 (enviadas comprovadas/afirmadas: 15); último ciclo `run-20261024T110009-add6b8` partial em 24/10 08:00; doctor: integridade ok, 0 violações de FK, WAL, trava livre, porta 8776 livre, `cv_builder` BLOQUEADO (P6) | estado real antes da W1 | painel fora do ar no momento da medição |
| `Get-ScheduledTask 'JOBOS Local Engine'` (PowerShell, 24/10) | State Ready; LastRunTime 24/10 08:00:01; LastTaskResult=2; NextRunTime 24/10 12:00:00 | execução agendada das 08:00 de 24/10 | 12:00 ainda não executada no momento da medição |
| `data/logs/run-cycle-2026-10-24.log` e `run-cycle-2026-10-23.log` (leitura) | 24/10 08:03: TechnipFMC HTTP 422 (única falha de leitura), `FIM codigo_saida=2 duracao=179.7s`; 23/10 18:02: TechnipFMC HTTP 422, `FIM codigo_saida=2 duracao=144.7s` | confirma as execuções agendadas de 23/10 18:00 e 24/10 08:00 | `data/logs/jobos-2026-10-24.log` está vazio (ver Bloqueios) |
| `backup --label verificacao-p1` | integridade ok, restauração verificada em pasta temporária | T50 | |
| `install-schedule.ps1 -DisableLegacy -WhatIf` e real | tarefa registrada; legadas desativadas com XML (`data/backups/scheduler/`) | P5 | |
| `Start-ScheduledTask 'JOBOS Local Engine'` | executou pelo Agendador: `LastTaskResult=2` (parcial propagado), 83,6 s, log `data/logs/run-cycle-2026-10-22.log` com run_id | execução real agendada | em 23/10, `data/logs/jobos-2026-10-23.log` está vazio; o ciclo das 08:00 não foi confirmado |
| análise 2ª execução | 166 alterações alertáveis → 159 eram enriquecimento/formatação (bug corrigido, DEC-016), 7 reais | classificação de mudanças | |
| painel no navegador (desktop e 375 px) | Visão geral, Vagas, Detalhe, Fontes renderizam com dados reais; sem erro de console no painel | P3 UI | ações de candidatura testadas só por API/testes, não clicadas em dados reais |
| portal antigo `/` | renderiza com dados do SQLite | reaproveitamento | CDN `cdn.apollo.rio.br` continua externo |
| 30/10: `pytest -p no:cacheprovider tests` | **406 passed**, exit 0. A linha final "N passed" não saiu na captura; a contagem é o número de marcas `.` nas linhas de progresso (sem `s`, `x` ou `F`) | laço manual, frescor, prazo do ciclo, CSP, comprovante, palavras-chave, quatro leitores registrados, guardas de segurança. O teste Oracle de detalhe conhecido usa `iso()`: a data fixa 22/10 tinha passado do TTL de 7 dias e o coletor reabria o detalhe de propósito | sem rede. O painel não foi clicado no navegador |
| 30/10: `node --check web/painel/painel.js` | exit 0 | o painel compilado | sem clique |
| 30/10: `cycle --dry-run --fixtures` | o relatório imprimiu `código=2`, status partial; análise `good_fit` 1 e `insufficient_data` 2, política `matching-v7`. SHA-256 do `jobos.sqlite3` igual antes e depois: `8864eea2bb1624998f01ea6dfef8fdbee7d87cbcbec381407d283d93a106e176` (215.068.672 bytes, WAL 0) | banco temporário. Aker, Airswift, Trident e ABS ficaram `skipped` (sem fixture) | `subsea7-sf` falha de propósito (`tests/fixtures/sources/subsea7-sf.json`) |
| 30/10: `install-schedule.ps1 -WhatIf` | exit 0. Plano: diários 08:00, 12:00, 14:00, 18:00, AtLogOn, evento de retorno da suspensão e evento 4801. WakeToRun desligado. Texto final: "WhatIf: nada foi alterado." | gatilhos só em memória | a tarefa existente não foi registrada de novo |
| 30/10: `jobos doctor` e `jobos status` (trava livre, 20:38 Brasília, janela entre ciclos) | doctor exit 0. `cv_kit` OK, `cv_builder` aviso, frescor aviso: último ciclo completo há 30,6 h, 5 horários perdidos (29/10 18:00, 30/10 08:00, 12:00, 14:00; o quinto não cabe na linha do doctor). Integridade ok, 0 violações de FK, porta 8776 livre. Status: 2.556 vagas (767 ativas), candidaturas `legacy_needs_review` 13 e `submitted_manual` 15, pendências 50 boa aderência sem envio, 0 CV em revisão, 13 legado. Último ciclo completo `run-20261029T170012-363ec0` em 29/10 14:00. Próximo horário 31/10 08:00, atrasado. 49 fontes, 32 com leitor ativo | estado real depois do registro dos leitores | abrir o CLI grava o cadastro das fontes. As quatro linhas passaram ao leitor novo. Nenhuma vaga foi encerrada. `altera-gupy` continua ligada. SHA-256 depois dessa gravação: `26e7ffc12b574f3cf754c1c570d8908d9735860d1342167eb46f04be2c4408b5` |

## Dados

Banco origem: `Artifact/jobs.db` SHA-256 `554aef34…a680d` (2.022 jobs, 4.200 events, 1.316 runs), intacto.
Banco canônico: `_system/data/jobos.sqlite3` (WAL).
Importações: `imp-sqlite-554aef34f39a` (1.885 vagas canônicas) e `imp-portal-a8f1034c3604` (155 vinculadas, 97 novas).
Após 1º ciclo real: 2.276 vagas (609 ativas, 184 ausentes não confirmadas, 1.483 não verificadas desde a importação).
Revisões de procedência em 22/10: 28 `legacy_needs_review`; enviadas comprovadas/afirmadas: 0 (histórico). Em 24/10 (`jobos status`): candidaturas `legacy_needs_review` 13 e `submitted_manual` 15; enviadas comprovadas/afirmadas: 15.
Backups: `data/backups/p0-…`, `…-pre-import` não necessário (banco vazio), `20261022T233616-verificacao-p1`; `data/backups/20261024T143940-pre-w1` (pre-w1, 24/10/2026: integridade ok, restauração verificada).
Em 30/10, `doctor`/`status`/`sources` atualizaram só o cadastro das fontes para os leitores da DEC-023. Nenhuma vaga foi encerrada e `altera-gupy` segue ligada. O dry-run com fixtures não alterou o arquivo do banco.

## Bloqueios específicos

- CV Builder (P6): código/esquema não está no workspace. Coleta, painel e análise seguem.
- SMTP: sem destinatário/credencial; `notifications.yaml` com `enabled: false`; preview em `data/outbox-preview/`.
- TechnipFMC: resolvido em 24/10 (W1b) — Workday inexistente; fonte migrada para `j2w_search` (careers.technipfmc.com). O dry-run ao vivo de 24/10 usou `max_details: 0`. O caminho de detalhe do j2w é exercitado pelos fixtures de `tests/test_collectors_ported.py`.
- Aker, Airswift, Trident e ABS: leitores reais registrados em 30/10 (DEC-023), sem coleta ao vivo. O "ok" dessas três primeiras na cobertura ainda é a leitura de 29/10 do leitor anterior. ABS está `never_run` no leitor novo. O próximo ciclo agendado chama os quatro sites.
- Empresas ainda sem leitor conhecido continuam `unconfigured`. `altera-gupy` não foi encerrada.
- Logger: resolvido em 24/10 (W1a) — o arquivo diário ficava vazio porque a CLI não emitia INFO; agora registra início/fim de comando, ciclo e fontes.
- Marcações antigas do `localStorage`: exigem exportação manual do navegador (snippet no README).

## Próxima ação exata

1. Rafael aprova, se quiser, o `install-schedule.ps1` de verdade. O `-WhatIf` de 30/10 não registrou os gatilhos de retorno da suspensão, logon e desbloqueio. Sem isso, notebook dormindo continua perdendo horário. O script e o Python no disco já valem para o próximo ciclo, inclusive o limite de 45 minutos.
2. Abrir o painel com `JOBOS.cmd`, gerar o currículo das primeiras vagas de boa aderência e revisar no Edge antes de enviar. São 50 vagas `good_fit` ativas sem candidatura. Gerar o currículo não envia.
3. Escrever títulos em português só se quiser trocar os que já existem no perfil. Criar `config/profile/answers_preapproved.json` com telefone, CPF, pretensão, regime e diversidade. O arquivo é ignorado pelo git. O JOBOS não inventa essas respostas.
4. Preencher o perfil da Gupy uma vez. Telefone e CPF ficam no Bitwarden.
5. Candidatar no próprio navegador e confirmar no painel com o SHA do currículo. Não há envio automático. A DEC-022 continua sem aceite.
6. Rotular 30–50 vagas se quiser a calibração (`matching-v8`). Revisar as 13 candidaturas legadas.

## Comandos para retomar

```powershell
Set-Location -LiteralPath 'D:\dev\_dev web\_rvalle-site\__VAGAS\_system'
& '.\.venv\Scripts\python.exe' -m jobos doctor
& '.\.venv\Scripts\python.exe' -m jobos status
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\show-status.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\start-dashboard.ps1'
```
