# Decisões

## DEC-001: Python local coordena, SQLite é autoridade

Estado: aceito
Contexto observado: legado Python (`Artifact/jobos`) e TS (`assets/*.ts`) gravam estados próprios (`jobs.db`, `jobs.json`).
Decisão: engine em `_system/src/jobos`, `.venv` próprio, CLI `python -m jobos`, banco `_system/data/jobos.sqlite3` (WAL, `synchronous=NORMAL`, foreign keys, `busy_timeout`). `jobs.json`/`jobs-data.js` viram projeções servidas pela API.
Motivo: uma autoridade de estado; o D: tem fsync lento (AUDIT §1).
Consequência: legado continua intacto e só é lido.
Validação: `doctor`, `status`, testes de importação.
Reversão: apagar `_system/data/jobos.sqlite3`; legado não muda.

## DEC-002: Migração preserva original e procedência incerta

Estado: aceito
Decisão: importação em nova base com cópia identificada por hash em `data/imports/<import_id>/`, `legacy_id_map`, payload legado integral (`legacy_payloads`), eventos e runs antigos em tabelas `legacy_*` com datas originais. Linhas legadas com o mesmo `source_id` (123 grupos) viram uma vaga canônica com várias referências (identidade forte); título/local parecido sem ID não funde.
Validação: T01-T04, contagens antes/depois em `data/imports/<id>/report.json`.

## DEC-003: Um leitor principal por fonte, em Python

Estado: aceito
Contexto: Python legado e TS cobrem as mesmas plataformas; TS mescla/fecha estado em `merge-jobs.ts`.
Decisão: adapters Python portados (sem importar o pacote legado, que colide no nome `jobos`). Bridge TS não é necessário nesta entrega; Oracle CE (ABS) fica `unconfigured`. Coletores devolvem `SourceBatch`; só `persistence.py` grava.
Alternativa descartada: chamar `refreshJobs()` (fecha vaga na primeira ausência).

## DEC-004: Perfil canônico separado de preferências

Estado: aceito
Decisão: `config/profile/master.json` (cópia de `rvalle.com.br-rafael.json`, versionada por SHA-256 em `profile_versions`) é autoridade de fatos. `config/preferences.yaml` guarda política (locais, exclusões) com campo `origin` por regra. `profile.yml` legado não é carregado.

## DEC-005: Candidatura presumida removida

Estado: aceito
Decisão: não existe conversão sugestão→enviada. 28 registros `applied` legados viram `legacy_needs_review` com valor original, data e eventos preservados; fora do total comprovado. Envio só por `application confirm` (`user_asserted`) ou prova de plataforma.

## DEC-006: Datas separadas

Estado: aceito
Decisão: `published_at` + `published_date_precision` + `published_date_source` + `published_raw`; `first_seen_at` (+ precisão), `last_seen_at`, `imported_at`, `content_changed_at`. `~AAAA-MM-DD` e textos relativos não viram publicação. Instantes em UTC; interface em `America/Sao_Paulo` (`tzdata`).

## DEC-007: Encerramento só por leitura completa no mesmo escopo

Estado: aceito
Decisão: `active → missing_unconfirmed → closed_confirmed`. Exige lote `complete`, `can_infer_absence`, mesmo `scope_id` do anúncio (ou `full_board`), sem queda anômala (>50% com base ≥10), 2 leituras completas consecutivas separadas por ≥6 h. Vaga com outra referência ativa continua ativa. Importados entram como `unknown` (não verificados) até a primeira observação.

## DEC-008: Aderência sem probabilidade

Estado: aceito
Decisão: análise determinística por requisito (atendido/parcial/lacuna/desconhecido) com JSON Pointer; cobertura por peso; nota só com cobertura ≥ 0,6; prioridade separada e transparente. `interview_prob` não é exibido. IA opcional fica desligada (`config/matching.yaml`).

## DEC-009: Isolamento de arquivos privados

Estado: aceito
Decisão: API em `127.0.0.1`, validação de Host/Origin, mutações exigem `X-JOBOS: 1` e origem própria, sem CORS. Estático só por allowlist: `index.html`, `sw.js`, `manifest.webmanifest`, `assets/` com extensões de site (sem `.ts`), e `_system/web/`. `_system`, `__VAGAS` inteiros, `.json` privados e banco nunca são servidos. Artefatos só por ID.

## DEC-010: CV Builder e WordPress depois

Estado: aceito
Decisão: P6 bloqueado até existir código/esquema do CV Builder no disco (não encontrado em `__VAGAS`). WordPress (P8) desligado; contrato observado registrado em REUSE-MAP.

## DEC-011: Porta 8766

Estado: aceito
Contexto: 8765 ocupada pelo servidor do rastreador de Correios (outro projeto).
Decisão: `config/app.yaml` usa 8766; `start-dashboard.ps1` verifica a porta e não encerra processo alheio.

Atualização em 23/10/2026: a 8766 passou a responder o WhatsApp Hub (`python -m http.server`, loopback, PID 19408, interpretador do Inkscape). Esse processo não foi encerrado. O painel do JOBOS passou para a porta 8776 em `config/app.yaml`. A regra de não encerrar processo alheio permanece.
Substituída em parte pela DEC-020 (porta).

## DEC-012: Tarefas legadas

Estado: aceito
Contexto: `jobos-vagas - ciclo 12h/18h` executam script em caminho inexistente e falham.
Decisão: `install-schedule.ps1` exporta XML para `data/backups/scheduler/` e desativa (não apaga) somente essas duas. `RVALLE-Correios-Jobos-1530` não é tocada.
Reversão: `Enable-ScheduledTask -TaskName 'jobos-vagas - ciclo 12h'`.

## DEC-013: Painel reaproveita o portal

Estado: aceito
Decisão: o portal JOBOS existente é servido sem edição, com `jobs.json`/`assets/jobs-data.js` gerados do SQLite no formato `Book` (IDs externos preservados para não quebrar `localStorage`). `POST /api/refresh` enfileira coleta (não executa no request). Telas operacionais novas (fontes, candidaturas, execuções, outbox) ficam em `_system/web/painel/` com a mesma linguagem visual, sem framework.

## DEC-014: Ajustes após a primeira operação real (22/10/2026)

Estado: aceito
Contexto observado: (1) detalhe Gupy `employability-portal.gupy.io/api/v1/jobs/{id}` respondeu 404 em todas as vagas; (2) o portal antigo faz `POST /api/refresh` a cada abertura; (3) análise de ~2.000 vagas numa única transação bloqueava mutações da API por mais de 30 s no D:.
Decisão: (1) detalhe Gupy pela página pública da vaga (`__NEXT_DATA__.props.pageProps.job`); (2) `/api/refresh` só enfileira ciclo se não houve ciclo nos últimos 60 min; (3) análise em transações de 100 vagas, com re-checagem dentro da transação; API devolve 503 legível se o banco estiver ocupado.
Validação: testes `test_gupy.py`, `test_portal_refresh_respects_cooldown`; ciclo real com 8/8 detalhes PRIO.
Reversão: código versionado no próprio pacote; política de análise identificada por `policy_version`.

## DEC-015: Política de análise versionada a cada mudança de regra

Estado: aceito
Decisão: toda mudança de regra de extração/avaliação incrementa `policy_version` em `config/matching.yaml` (hoje `matching-v6`). Análises anteriores ficam preservadas por versão de vaga/perfil/política; o painel mostra a mais recente da versão atual da vaga.
Consequência: v1 a v5 existem no banco como histórico de calibração do mesmo dia.

## DEC-016: Enriquecimento e formatação não são "vaga alterada"

Estado: aceito
Contexto observado: a 2ª execução real (via Agendador, `run-20261022T235202-e93297`) gerou 166 eventos `job.changed` alertáveis; 125 eram descrição que só chegou após o limite de detalhes ou primeira leitura sobre texto legado, e 34 eram diferenças só de formatação (marcadores "- ", `&nbsp;`, espaços).
Decisão: hash de conteúdo `norm-v2` ignora caixa, acentos, pontuação e marcadores; antes de criar versão, a versão atual é recalculada com a normalização vigente; descrição tardia/legado vira `job.enriched` (não alerta). Os 159 eventos daquele run foram reclassificados (`job.enriched`/`job.reformatted`, `alertable=0`, motivo no payload) e o rascunho do resumo desse run foi cancelado (nunca enviado). Versões já gravadas foram mantidas como histórico.
Validação: `test_late_description_is_enrichment_not_alert`, `test_formatting_only_change_creates_no_version`; restaram 7 alterações reais.

## DEC-017: Projeção pública regravada no workspace a cada ciclo

Estado: aceito
Contexto observado: auditoria de 23/10/2026: `__VAGAS/jobs.json` e `assets/jobs-data.js` eram um snapshot de 08/10; quem abre o portal direto do arquivo via dezenas de vagas a menos (ex.: Qualidados 8 de 37, VINCI 1 de 54).
Decisão: `exports.portal_files: true` em `config/app.yaml` faz o ciclo real regravar os dois arquivos com o `Book` do SQLite (somente título, empresa, local, URL, datas, estado do anúncio; nada de candidatura, nota ou perfil). Originais guardados uma vez em `data/backups/portal-files-original/`. Dry run e fixtures nunca gravam.
Reversão: `portal_files: false` e restaurar os originais do backup.

## DEC-018: Confirmação individual de anúncios antigos (probe)

Estado: aceito
Contexto: anúncios importados ou de escopos antigos ficavam "não verificados" para sempre quando a listagem atual não os cobre (filtro por país/escritório, mudança de escopo).
Decisão: depois da coleta, até 15 por fonte e 120 por ciclo são checados um a um pela função `probe()` do adapter (Gupy: status da página da vaga; Greenhouse: `/jobs/{id}`; demais conforme cada adapter). `gone` conta como evidência de ausência (2 evidências com ≥ 6 h fecham); `alive` zera a contagem; erro de rede é `unknown` e não muda nada. Fonte com leitura falha não é sondada.

## DEC-019: Etiquetas de candidatura

Estado: aceito
Decisão: "Auto aplicado" = marcado pelo sistema antigo sem ação comprovada (13; não conta como enviada). "Aplicado" = envio afirmado pelo usuário, incluindo as 15 marcações manuais originais do sistema antigo, confirmadas pelo usuário em 22/10/2026 (`application confirm-legacy-manual --apply`, origem `user_asserted`, data original 24/08/2026). "Aplicado ✓ comprovado" = prova da plataforma.

## DEC-020: Porta 8776 para o painel

Estado: aceito; substitui a porta da DEC-011 (8766). A DEC-011 segue como histórico.
Contexto observado: a DEC-011 escolheu 8766 porque 8765 estava ocupada pelo rastreador de Correios. Em 23/10/2026 a 8766 passou a responder o WhatsApp Hub (`python -m http.server`, loopback, PID 19408, interpretador do Inkscape). Verificado em 24/10/2026 na worktree: `config/app.yaml` linha 5 traz `port: 8776` com o comentário "8766 WhatsApp Hub"; `scripts/windows/start-dashboard.ps1` usa 8776 como padrão (linhas 7, 21 e 122); `JOBOS.cmd` chama `scripts\windows\start-dashboard.ps1` sem porta própria; `src/jobos/cli.py` tem 8776 como padrão; `scripts/windows/install-schedule.ps1`, `show-status.ps1` e `remove-schedule.ps1` usam 8776. O `start-dashboard.ps1` fica em `scripts/windows/`, não na raiz. Em 24/10/2026, `jobos doctor` reportou `porta_painel: 127.0.0.1:8776 livre`.
Decisão: o painel e a API do JOBOS usam `127.0.0.1:8776` (`server.port` em `config/app.yaml`). A 8766 fica com o WhatsApp Hub, e nenhum processo alheio é encerrado. `start-dashboard.ps1` continua verificando a porta e não encerra processo de outro projeto.
Motivo: a 8766 está ocupada por processo de outro projeto; trocar a porta do painel é reversível e não afeta o WhatsApp Hub. A 8776 estava livre.
Alternativas descartadas: encerrar o WhatsApp Hub na 8766 (processo alheio, viola a regra da DEC-011); usar a 8765 (ocupada pelo Correios); porta aleatória (quebra a URL fixa `http://127.0.0.1:8776/painel/` do atalho e do README).
Consequência: README, `docs/PROGRESS.md` e os scripts apontam para 8776. A origem do navegador muda com a porta, e o `localStorage` é por origem, então marcações feitas em `127.0.0.1:8766` não aparecem em `127.0.0.1:8776` (ver exportação manual em PROGRESS, Bloqueios). Menções a 8766 em `docs/PROGRESS.md` (linha do P3) e em `docs/AUDIT.md` e `docs/CONFLICTS.md` são registros históricos e não foram alterados.
Validação: `grep` de 8776 em `config/app.yaml`, `scripts/windows/start-dashboard.ps1`, `src/jobos/cli.py` e `README.md` (24/10/2026); `jobos doctor` com `porta_painel 127.0.0.1:8776 livre` (24/10/2026); na verificação de 23/10 registrada em PROGRESS (Verificações), `/api/health` respondeu 200 `jobos-local` na 8776.
Reversão: trocar `server.port` em `config/app.yaml` e os padrões 8776 de `cli.py` e dos `scripts/windows/*.ps1` de volta. Só faz sentido com a 8766 livre, ou seja, depois que o WhatsApp Hub for encerrado pelo dono do processo.
