# Progresso real do JOBOS

Atualizado em: 24/10/2026
Ambiente: Windows 11 nativo; Python 3.12.10 em `_system\.venv` (lock em `requirements.lock`); Node 24 para `node --check` do painel e para compilar `web/painel/src/preparo.ts` com o esbuild 0.25.10 de `__core.js`
Raiz confirmada: `D:\dev\_dev web\_rvalle-site\__VAGAS\_system`
Fase atual: P0 a P5 implementados e verificados; ondas W0/W1 do `docs/EXECUTION-PLAN-2026-10-23.md` concluídas (24/10); kit de CV local (P3.1-R) substitui o bloqueio do CV Builder para o caminho principal; P4-R+ não iniciados
Última entrega verificável: o painel abre como aplicativo local por `JOBOS.cmd` (janela `--app`). Porta do painel: 8776, porque a 8766 está com o WhatsApp Hub.

## Concluído

- [x] P0: auditoria (`AUDIT.md`, `SOURCE-COVERAGE.md`, `REUSE-MAP.md`, `CONFLICTS.md`, `DECISIONS.md`); backup P0 em `data/backups/p0-20261022T151356Z/`
- [x] P1: pacote `src/jobos`, CLI estrita, migração v1, importação idempotente (SQLite legado + `jobs.json`), perfil versionado, 28 candidaturas legadas em revisão
- [x] P2: 11 adapters (`SourceBatch` com status/completude/escopo), persistência com versões, ausência protegida (2 leituras completas + 6 h + mesmo escopo + guarda de queda anômala), baseline sem alerta, relações de possível republicação
- [x] P3: API FastAPI em 127.0.0.1:8766 (Host/Origin/X-JOBOS, allowlist estática), fila `work_items` com lease e worker, portal antigo servido sem edição com `jobs.json`/`jobs-data.js` gerados do SQLite, painel operacional `/painel/` (8 seções)
- [x] P4: análise determinística por requisito (atendido/parcial/lacuna/desconhecido) com JSON Pointer, cobertura, nota só com cobertura ≥ 60%, função pelo `role_fit_tree`, preferências visíveis, prioridade separada; política `matching-v6`
- [x] Execução real pelo Agendador do Windows verificada (código 2 = parcial pela TechnipFMC)
- [x] P5: outbox persistente (rascunho/preview .txt/.html/.eml), transporte SMTP separado e desligado, estados accepted/unknown/failed_transient, scripts Windows, tarefa `JOBOS Local Engine` registrada (08/12/14/18 h)
- [x] Aplicativo local: `JOBOS.cmd` sobe o servidor se precisar e abre `/painel/` em janela de aplicativo (Edge ou Chrome `--app`). Se `/api/health` já responder `jobos-local`, só abre a janela. O manifesto fica em `/painel/manifest.webmanifest`, com `scope` e `start_url` em `/painel/`. Duplo clique no `index.html` do disco não é o aplicativo. `preparo.ts` continua fora da allowlist.
- [x] Preparo por vaga no detalhe: `src/jobos/matching/prepare.py` seleciona, na leitura, textos já escritos no perfil (requisito atendido ou parcial, wording seguro, história, headline). Headline automático só quando um cobre mais domínios do que o seguinte. A página em TypeScript está em `web/painel/src/preparo.ts` e o navegador recebe `web/painel/preparo.js`. Não grava CV, não marca envio e não chama IA. A política `matching-v6` permanece.

## Arquivos principais

`src/jobos/` (cli, pipeline, persistence, collectors/*, matching/*, notifications/*, api/*, legacy/*, storage/*), `config/*.yaml`, `config/profile/master.json` (cópia do perfil), `web/painel/*` (fonte `src/preparo.ts`, saída `preparo.js`), `scripts/build-preparo.mjs`, `scripts/windows/*.ps1`, `tests/*` (322 testes, medição de 23-24/10/2026), `docs/*`, `README.md`, `CLAUDE.md`.

## Verificações

| Comando/teste | Resultado real | O que verifica | Limite |
|---|---|---|---|
| `pytest -p no:cacheprovider tests` | **126 passed** (25 s) em 22/10 | T01-T04, T06-T18, T20-T27, T31-T37, T40-T45, adapters offline | sem rede |
| `pytest -p no:cacheprovider tests` | **141 passed** (37 s) em 23/10 | suíte atual, com `tests/test_prepare.py` e o campo `support` no detalhe | sem rede |
| `pytest -p no:cacheprovider tests` | **322 passed** (exit 0), medição de 23-24/10 | suíte atual | não repetida na W0 |
| W1 (24/10, worktree `w0-w1`): `pytest -p no:cacheprovider tests` | **387 passed, 1 xfailed** (exit 0) | +T25, T38, T42, T43, saídas 4/5, `fuso_windows`, log diário (W1a); matriz de saúde das fontes (W1b, 14 testes); kit de CV T28/T29/T47 + `cv build` (W1c, 19 testes) | xfail estrito: extrator de requisitos aceita HTML/instruções após "Requisitos:" (W2) |
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

## Dados

Banco origem: `Artifact/jobs.db` SHA-256 `554aef34…a680d` (2.022 jobs, 4.200 events, 1.316 runs), intacto.
Banco canônico: `_system/data/jobos.sqlite3` (WAL).
Importações: `imp-sqlite-554aef34f39a` (1.885 vagas canônicas) e `imp-portal-a8f1034c3604` (155 vinculadas, 97 novas).
Após 1º ciclo real: 2.276 vagas (609 ativas, 184 ausentes não confirmadas, 1.483 não verificadas desde a importação).
Revisões de procedência em 22/10: 28 `legacy_needs_review`; enviadas comprovadas/afirmadas: 0 (histórico). Em 24/10 (`jobos status`): candidaturas `legacy_needs_review` 13 e `submitted_manual` 15; enviadas comprovadas/afirmadas: 15.
Backups: `data/backups/p0-…`, `…-pre-import` não necessário (banco vazio), `20261022T233616-verificacao-p1`; `data/backups/20261024T143940-pre-w1` (pre-w1, 24/10/2026: integridade ok, restauração verificada).

## Bloqueios específicos

- CV Builder (P6): código/esquema não está no workspace. Coleta, painel e análise seguem.
- SMTP: sem destinatário/credencial; `notifications.yaml` com `enabled: false`; preview em `data/outbox-preview/`.
- TechnipFMC: resolvido em 24/10 (W1b) — Workday inexistente; fonte migrada para `j2w_search` (careers.technipfmc.com). Detalhe por vaga ainda não exercitado para esta fonte.
- ABS (Oracle CE) e 15 empresas sem ATS conhecido: `unconfigured`.
- Logger: resolvido em 24/10 (W1a) — o arquivo diário ficava vazio porque a CLI não emitia INFO; agora registra início/fim de comando, ciclo e fontes.
- Marcações antigas do `localStorage`: exigem exportação manual do navegador (snippet no README).

## Próxima ação exata

1. Onda W2 do `docs/EXECUTION-PLAN-2026-10-23.md`: corrigir o extrator de `matching/requirements.py` (T42 em xfail estrito) e rotular 30–50 vagas para a calibração P2-R.
2. Revisar no painel as 13 candidaturas legadas restantes (Candidaturas → "Procedência legada a revisar").
3. Conferir no painel (Fontes) que a TechnipFMC passa a "ok" após o primeiro ciclo real com `j2w_search`.

## Comandos para retomar

```powershell
Set-Location -LiteralPath 'D:\dev\_dev web\_rvalle-site\__VAGAS\_system'
& '.\.venv\Scripts\python.exe' -m jobos doctor
& '.\.venv\Scripts\python.exe' -m jobos status
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\show-status.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\start-dashboard.ps1'
```
