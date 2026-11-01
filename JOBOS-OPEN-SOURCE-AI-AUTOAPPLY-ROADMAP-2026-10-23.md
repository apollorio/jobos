# JOBOS | Roadmap AS-BUILT, plano de conclusão ZERO-AI

**Revisão:** 23/10/2026  
**Repositório analisado:** [apollorio/jobos](https://github.com/apollorio/jobos), branch `main`, commit `a85897cb39f5ade6ef67454216c064e8c65786ec`, publicado em 23/10/2026 às 20:05:54 UTC.  
**Workspace operacional:** `D:\dev\_dev web\_rvalle-site\__VAGAS\_system`, dentro de `__VAGAS`.  
**Autoridade desta revisão:** arquivos do commit indicado, especialmente `CLAUDE.md`, `README.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/AUDIT.md`, `config/*.yaml`, `src/jobos/**`, `tests/**`.  
**Modo exigido:** núcleo 100% funcional sem IA, modelos, embeddings, APIs pagas nem assinaturas; qualquer IA futura deve ser plug-in opt-in.  
**Condição:** análise estática do repositório privado conectado. Não houve clone local, execução do código na máquina Windows, inspeção do SQLite privado, login em ATS, testes de browser nem atualização no repositório remoto. Todos os números de runtime abaixo vêm da documentação versionada, não de nova medição.

---

## 1. Decisão executiva e correção do plano anterior

**O projeto não está começando do zero.** O repositório atual já contém um engine Python com persistência e histórico preservado, descoberta multi-ATS, matching determinístico, API/painel local, scripts operacionais Windows, agendamento, outbox e testes.

Nosso plano genérico anterior subestimou o que já foi construído. Não criar um `jobos/core` paralelo; não refazer `storage`, `pipeline`, `matching`, `API` ou novo dashboard. A implementação incremental deve aproveitar os componentes existentes e suas decisões documentadas.

### O que priorizar agora

1. **P0-R: Reconciliação operacional e documental:** confirmar saúde do Windows/agendador, corrigir divergências de documentação e levantar um baseline do banco *sem alterar dados*.
2. **P1-R: Confiabilidade das fontes existentes:** resolver as falhas reais que afetam a busca e reduzir fontes `unconfigured` por impacto, sem fazer coleta agressiva.
3. **P2-R: Valor imediato do matching:** calibrar o `matching-v6` contra vagas de verdade, melhorar explicações e filtros por configuração, sem instalar IA.
4. **P3-R: Pacote de CV independente do Builder ausente:** gerar HTML imprimível e currículo factual por vaga com o preparo que já existe. Compatibilidade com o CV Builder real fica opcional.
5. **P4-R: Candidatura assistida real:** criar o primeiro módulo de *application automation*, separado dos coletores de vagas, começando por fixture local e depois TOTVS; Gupy e SuccessFactors em ondas distintas.
6. **P5-R: Comprovantes, idempotência e observabilidade:** tornar rastreável cada tentativa, com revisão humana antes do envio e sem candidatura fantasma.
7. **P6-R: Piloto supervisionado, métricas e manutenção:** rodar uma pequena fila de vagas boas, ajustar selectors e priorizar entrevistas.

IA semântica ou generativa **não faz parte de nenhuma dependência acima**, mesmo como recomendação de instalação. Pode ser ignorada indefinidamente.

---

## 2. Inventário real: existente, parcial, ausente

| Subsistema | Evidência no repo | Estado fundamentado | Diretriz |
|---|---|---|---|
| Entry point e CLI | `src/jobos/cli.py`, `src/jobos/__main__.py`, `JOBOS.cmd` | Implementados; CLI estrita e lançador | Preservar comandos e contratos |
| Configuração | `config/app.yaml`, `sources.yaml`, `preferences.yaml`, `matching.yaml` | Implementada; regras e fontes versionadas | Não duplicar em outro YAML |
| Coleta de anúncios | `src/jobos/collectors/{gupy,totvs,j2w,workday,greenhouse,...}.py` | Leitores por plataforma implementados; falhas pontuais | Melhorar/adicionar fontes na arquitetura existente |
| Deduplicação e estados | `src/jobos/persistence.py`, `domain/identity.py`, `storage/repo.py` | Implementados | Não voltar ao hash título/local como ID principal |
| Histórico e SQLite | `storage/db.py`, `storage/migrations/0001_init.sql` e `0002_probe.sql` | SQLite canônico + WAL; migração do legado documentada | Mudanças só em migração nova e testada |
| Análise sem IA | `matching/analyze.py`, `requirements.py`, `evidence.py`, `preferences.py` | Implementada; política `matching-v6` e evidências JSON Pointer | Calibrar, não substituir |
| Pré-preparo factual | `matching/prepare.py`, `web/painel/src/preparo.ts` | Implementado: seleciona frases existentes; `writes_cv=false` e `sends_application=false` | Construir pacote de CV em cima disso |
| PDF/CV Builder | `docs/PROGRESS.md`, `_blueprint/01-ROADMAP.md` | **Não implementado** no repositório; integração com Builder ausente | Entregar fallback local, mantendo Builder como integração futura |
| Processo de candidatura | `applications/service.py`, `domain/states.py` | Estados, confirmações e histórico existem | Expandir sem romper origens/evidências |
| Preenchimento autenticado | Não há pacote `applications/adapters/` nem Playwright nas dependências | **Não implementado** no snapshot | Novo subsistema P4-R, por ATS |
| API local | `api/app.py`, `api/worker.py` | Implementada: endpoints, proteção de mutações, fila | Acrescentar rotas por versão, sem reescrever |
| Painel | `web/painel/index.html`, `painel.js`, `painel.css`, `preparo.js` | Implementado, oito seções documentadas | Evoluir páginas existentes |
| Agendamento | `scripts/windows/install-schedule.ps1`, `run-cycle.ps1`, `show-status.ps1` | Registrado e testado segundo `PROGRESS` | Verificar execução atual antes de modificar |
| Notificações | `notifications/outbox.py`, `transport.py` | Outbox, preview e estados implementados; SMTP desligado | Nenhuma credencial necessária para operação local |
| Publicação do portal | `exports/portal.py`, `config/app.yaml` | Projeção unidirecional pública do SQLite configurada | Não incluir perfil/candidatura privados |
| Integração WordPress | `docs/DECISIONS.md`, `REUSE-MAP.md` | Desativada por decisão explícita | Fora do caminho crítico |
| Tests | `tests/*.py`, `tests/fixtures` | `PROGRESS.md` registra 141 testes aprovados em 23/10 | Reexecutar no PC; resultado relatado, não reverificado aqui |

### Dados relatados, não recontados nesta sessão

- Auditoria real do legado em `docs/AUDIT.md`: **2.022 vagas**, **4.200 eventos** e **1.316 execuções** no `Artifact/jobs.db`, em vez dos 1.118/2.295/251 de um anexo anterior.
- `docs/PROGRESS.md` relata **2.276 vagas canônicas** após o primeiro ciclo real, com **609 ativas**, **184 ausentes não confirmadas** e **1.483 ainda não verificadas após importação**.
- Os **28 registros antigos** com estado “applied” não são automaticamente 28 candidaturas comprovadas.
- Há **divergência documental a reconciliar**: `docs/PROGRESS.md` ainda cita 28 casos `legacy_needs_review` e 0 envios afirmados, enquanto `docs/DECISIONS.md` (DEC-019) declara 15 marcações manuais confirmadas em 22/10. **Não escolher um número por adivinhação**: o SQLite atual e os eventos de auditoria devem decidir.
- `config/sources.yaml` no commit atual lista aproximadamente **49 definições de fontes** (contagem textual de `source_id:`), incluindo **15 com `primary_adapter: null`** e **3 marcadas `enabled: false`**. Contar com parser YAML no PC, considerando fontes multi-tenant e duplicatas intencionais.
- Fonte da configuração é `config/sources.yaml`; `docs/SOURCE-COVERAGE.md` é um snapshot anterior, não autoridade operacional.
- Repositório `main` contém código e configurações, **não contém o banco, o perfil privado, .env ou os artefatos pessoais**, conforme o commit e `README`. Sem esses dados, esta auditoria não permite validar verdade profissional nem status ao vivo.

---

## 3. Arquitetura real que deve continuar sendo SSOT

```text
D:\dev\_dev web\_rvalle-site\__VAGAS\
  ├─ Artifact/                         legado, somente leitura
  ├─ jobs.json / assets/jobs-data.js    projeções do SQLite, não bases independentes
  └─ _system/
     ├─ JOBOS.cmd                       entrada desktop existente
     ├─ pyproject.toml                  dependências reais, SEM IA e SEM Playwright hoje
     ├─ requirements.lock
     ├─ CLAUDE.md                       regra operacional para agentes
     ├─ config/
     │  ├─ app.yaml                     porta 8776, horários e recursos
     │  ├─ matching.yaml                política matching-v6
     │  ├─ preferences.yaml             preferências, nunca fatos profissionais
     │  ├─ sources.yaml                 cadastro autoritativo das fontes
     │  └─ profile/master.json          privado/local; não está no GitHub
     ├─ src/jobos/
     │  ├─ cli.py, pipeline.py, persistence.py
     │  ├─ storage/                     SQLite, migrações, queries
     │  ├─ collectors/                  somente anúncios públicos
     │  ├─ matching/                    evidências e preparo sem IA
     │  ├─ applications/                estado/histórico; preencher ATS AINDA NÃO existe
     │  ├─ api/                         FastAPI + worker + fila
     │  ├─ notifications/               outbox, SMTP opcional desligado
     │  └─ exports/
     ├─ web/painel/                     UI existente + TS compilado do preparo
     ├─ scripts/windows/                operação e scheduler existentes
     ├─ docs/                           estado real e decisões
     ├─ tests/
     └─ data/                           DB, backups, logs, sessões; privado/ignorado pelo Git
```

**SSOT por tipo de informação:**

| Informação | Autoridade | Nunca tratar como autoridade |
|---|---|---|
| Histórico, estágio, candidatura | `data/jobos.sqlite3` | `jobs.json`, HTML, localStorage |
| Fatos da carreira | `config/profile/master.json` (privado) | CV gerado, resposta IA, preferências |
| Preferências | `config/preferences.yaml` | Fatos da experiência |
| Score e metodologia | `config/matching.yaml` e código `matching` | Nota legada ou “chance de entrevista” |
| Fontes, tenants e limites | `config/sources.yaml` | Tabelas históricas de documentação |
| Arquitetura aprovada | `docs/DECISIONS.md` + `CLAUDE.md` | Roadmap anterior incompatível |
| Estado dos testes e blockers | `docs/PROGRESS.md`, após revalidação | Afirmações baseadas somente em memória |
| HTML gerado para portal antigo | `exports/portal.py` | Qualquer segunda lógica de gravação |

**Invariantes que NÃO podem regredir:**

1. Nunca executar `Artifact/jobos` via import; nome de pacote colide com o novo.
2. SQLite em WAL + `synchronous=NORMAL` por fsync lento no D:.
3. Fonte `failed/partial` não fecha vagas; encerramento depende de duas leituras completas de mesmo escopo com intervalo mínimo de 6 h e guarda de queda anômala.
4. IDs fortes por plataforma/tenant/external ID; preservar eventos e referências históricas.
5. Data publicada ≠ primeira detecção ≠ importada; instantes UTC, exibição Brasília.
6. Enviado só com origem `user_asserted` ou confirmação de plataforma; `submitted_verified` exige evidência.
7. Não chamar `interview_prob` de probabilidade confiável, nem inventar certificados ou anos.
8. API em `127.0.0.1`, arquivos privados não servidos, mutações protegidas por Host/Origin e `X-JOBOS`.
9. Dry-run em base temporária, sem efeitos reais; fixtures nunca no banco do usuário.
10. Não ligar SMTP, WordPress, serviço pago ou IA para habilitar recursos do core.
11. Não editar nem encerrar outros projetos na porta 8765 ou 8766. `config/app.yaml` aponta **8776**.
12. Editar fonte TypeScript `web/painel/src/preparo.ts`, depois gerar `preparo.js` com `scripts/build-preparo.mjs`; não divergir manualmente as duas versões.

---

## 4. Divergências / riscos já identificados no próprio snapshot

| ID | Constatação | Evidência | Ação e prioridade |
|---|---|---|---|
| DR-01 | O roadmap anterior presume quase zero infraestrutura, mas P0-P5 já existem | `docs/PROGRESS.md` | Substituir plano de reimplementação pelo backlog delta. **P0** |
| DR-02 | Referências antigas de porta 8766 conflitam com porta atual 8776 | `docs/DECISIONS.md` DEC-011, `docs/PROGRESS.md` vs `config/app.yaml`/`README` | Corrigir documentação, nunca trocar portas cegamente. **P0** |
| DR-03 | Contagem e status das 28 candidaturas legadas não batem entre documentos | `PROGRESS.md` vs `DECISIONS.md` DEC-019 | Consultar banco read-only, documentar agrupamento. **P0** |
| DR-04 | `PROGRESS` não confirma ciclo 08:00 do dia 23/10 | `docs/PROGRESS.md` | Diagnosticar Task Scheduler/logs, sem reinstalação automática. **P0** |
| DR-05 | TechnipFMC responde HTTP 422 para tenant/site configurado | `PROGRESS.md`, `sources.yaml` | Descobrir URL oficial correta com inspeção pública autorizada; teste isolado. **P1** |
| DR-06 | Source coverage anterior difere do YAML atual (ex.: Brava, Ocyan, DOF) | `SOURCE-COVERAGE.md`, `sources.yaml` | Gerar matriz automaticamente do YAML e resultados, não alterar o YAML para seguir documentação antiga. **P1** |
| DR-07 | 15 fontes `unconfigured` e ABS Oracle CE sem coletor | `sources.yaml`, `SOURCE-COVERAGE.md` | Priorizar pelo valor para a carreira; não “coletar” com falso sucesso. **P1** |
| DR-08 | Matching determinístico existe, mas não há avaliação atual rotulada suficiente documentada para precisão | `matching/analyze.py`, `matching-v6` | Calibrar em amostra de vagas e manter versionamento. **P2** |
| DR-09 | Preparo é apenas seleção de textos, não um CV/PDF pronto | `matching/prepare.py`, testes de preparo | Criar pacote factual sem esperar Builder desconhecido. **P3** |
| DR-10 | Coletores Gupy/TOTVS/SAP não fazem login/aplicação | `collectors/*.py`, `applications/service.py` | Desenvolver adaptadores de formulário separados dos coletores. **P4** |
| DR-11 | Nenhum Playwright como dependência nem suíte de ATS em browser | `pyproject.toml`, `requirements.lock`, `tests/` | Adicionar dependência em grupo `ats`, nunca forçar em coleta/CLI. **P4** |
| DR-12 | O código tem tabela `artifacts` e rotas para download, mas o CV Builder está ausente | `0001_init.sql`, `api/app.py` | Reutilizar storage/rotas com validação de path/hash; migração apenas se faltarem campos. **P3** |
| DR-13 | Projeção pública de vagas grava JSON no workspace pai | `config/app.yaml` DEC-017 | Validar redaction, atomicidade, paths e efeitos de sync/hosting; nunca incluir dados privados. **P0/P6** |
| DR-14 | Retomar trabalho do projeto exige Python da venv, não o Python do Inkscape no PATH | `docs/AUDIT.md`, `README` | Usar exclusivamente `.\.venv\Scripts\python.exe` no Windows. **P0** |

Diferenciar **bug confirmado**, **divergência de documentação**, **recurso ainda não implementado** e **risco não testado**. Esta tabela usa essas categorias sem transformá-las em falha reproduzida no runtime desta sessão.

---

## 5. Backlog detalhado por ondas de entrega

### Fase P0-R: Baseline operacional e integridade (executar antes de mexer no código)

**Objetivo:** conhecer o estado do PC e do banco no momento da implantação; não destruir progresso.

**Passos:**
1. Abrir `CLAUDE.md`, `docs/PROGRESS.md` e `docs/DECISIONS.md` completos no workspace real.
2. `git status --short`, branch e commit local: verificar se o clone do Windows corresponde ao SHA acima e preservar alterações não commitadas.
3. Executar (sem alterar candidaturas) `doctor`, `status`, `show-status.ps1` e `pytest` via venv do projeto.
4. Registrar uso de RAM, espaço livre de D:/C:, disponibilidade do Edge/Chrome e porta 8776. Não instalar nenhuma IA.
5. Reconciliar SQLite: contagens atuais de vagas ativas/desconhecidas, sources, runs, work_items, aplicações por `prep_state` e `provenance`, evidências e `legacy_needs_review`.
6. Inspecionar o último ciclo programado por data/hora e resultado real; 0/2/3/4/5 têm significado distinto segundo CLI. Não afirmar “agendador saudável” porque a tarefa está cadastrada.
7. Gerar backup consistente usando o comando já implementado `jobos backup` antes da primeira migração ou escrita relevante.
8. Atualizar `docs/PROGRESS.md` e, se confirmado por leitura, corrigir porta DEC-011 sem apagar a decisão histórica: registrar um adendo DEC-020 sobre 8776.
9. Revisar exportação `jobs.json` / `assets/jobs-data.js` para evitar que o conteúdo público inclua `application`, `profile`, `private evidence` ou caminhos de arquivos.
10. Reconciliar as 15 marcações manuais e 13 “auto aplicadas” antigas sem nova confirmação implícita.

**Arquivos-alvo:** `docs/PROGRESS.md`, `docs/DECISIONS.md`, testes de operações; `src/jobos/status.py` e scripts somente se um defeito for comprovado.

**Aceite:** relatório datado com SHA local, comando, exit code, estado do DB, divergências resolvidas ou explicitamente abertas. Backups com restore testado. Nenhuma alteração silenciosa de candidatura.

### Fase P1-R: Saúde das fontes e cobertura útil

**Objetivo:** melhor descoberta de vagas relevantes, sem sacrificar precisão do histórico.

**Passos:**
1. Transformar `config/sources.yaml` + resultados `source_runs` em matriz viva no painel: `source_id`, empresa, plataforma, leitor, status, última execução, último sucesso, duração, vagas novas, taxa de detalhamento, warnings, escopo e URL pública.
2. Tratar TechnipFMC `422` em isolamento. Verificar URL de carreiras e tenant/site públicos; acrescentar fixture da resposta real saneada. Não construir chamadas privadas de empregador.
3. Revalidar Brava (tenants múltiplos), Ocyan e DOF segundo YAML **mais recente**; confirmar que a agregação multi-tenant não duplica IDs nem induz fechamento de vaga válida.
4. Selecionar primeiras fontes `unconfigured` pelos cargos prováveis e empresas prioritárias do Rafael: ABS, Constellation, recrutadoras de marítimo/O&G, e outras de acordo com decisões explícitas dele. Não prometer que todas são automatizáveis.
5. Criar leitor apenas para fonte pública legítima e estável; resultado `unconfigured` ou `blocked` é aceitável quando acesso não existe. Ações em conta do candidato pertencem à fase P4-R.
6. Para anúncios que sumiram por mudança de escopo, reutilizar `probe()` existente e política DEC-018 (limites `probe_per_source=15`, `probe_per_cycle=120`); não “otimizar” fechando instantaneamente.
7. Validar vigência da vaga no detalhe imediatamente antes de iniciar processo de candidatura; salvar `checked_at` e motivo para `closed`, `unknown` ou `active`.
8. Usar simulações de HTML/JSON para `format_changed`, paginação interrompida, rate limiting, 403/429/5xx, fontes sem vagas e filtros que retornam vazio.
9. Manter `max_parallel_sources=4` existente por padrão até benchmark real: 4 consultas HTTP não equivalem a 4 modelos de IA. Ajustar por carga medida, não por presunção.

**Reusar:** `collectors/base.py`, `registry.py`, `http.py`, `pipeline.py`, `persistence.py`.  
**Adicionar:** testes de cada mudança e relatório automatizado de `sources.yaml` vs cobertura.  
**Aceite:** nenhuma fonte com falha marca anúncio fechado; todo caso de zero vagas tem evidência de completude; fonte 422 diagnosticada com resultado explícito; escopo e versão rastreáveis.

### Fase P2-R: Matching e shortlist forte sem IA

**Objetivo:** conseguir recomendações realmente úteis, com evidências e sem falsos números de contratação.

**Estado existente:** `matching-v6`, score de requisitos com status `met/partial/gap/unknown`, cobertura mínima 60%, `role_fit`, preferência separada de fit, prioridade e fatos por JSON Pointer.

**Tarefas:**
1. Não criar `score2.py`, Chroma, FastEmbed ou outra autoridade. Reforçar `src/jobos/matching/analyze.py`, `requirements.py`, `evidence.py` e `config/matching.yaml`.
2. Montar 30–50 vagas reais rotuladas pelo Rafael: boas, limítrofes, descartáveis e desconhecidas. Guardar apenas descrição e evidências permitidas; documentar versão do perfil e da política.
3. Separar **gate real** (requisito obrigatório indisponível), **preferência** (Rio versus outras bases), **incerteza** (local desconhecido) e **prioridade** (empresa, frescor, setor). Um score alto não sobrepõe veto verdadeiro; preferência não oculta anúncios.
4. Testar sinônimos marítimos/offshore/planejamento, português/inglês, sem inflar “Python projeto pessoal” como experiência corporativa. Engenharia, superintendent, mobilização, P6 em desenvolvimento, PMP não certificado e reciclagem pendente devem respeitar `truth_boundaries`.
5. Adicionar dicionários YAML simples e versionados **se** melhorar falso positivo/negativo nos exemplos; não duplicar `role_fit_tree` que já existe no perfil.
6. Se buscas textuais forem lentas, avaliar SQLite FTS5 como **otimização futura**, após medir. A migração atual `0001_init.sql` não cria FTS5; não tratá-lo como implementado. FTS5 não precisa de modelo de IA.
7. Registrar `score_version`, `profile_id`, `job_version_id`, `gaps` e as evidências que justificaram a recomendação.
8. Medir `precision@8` e revisões humanas, sem converter aderência em probabilidade de entrevista.
9. Não introduzir penalidade automática por estar desempregado há quase dois anos; isso já foi removido como regra legado (ver `CONFLICTS`).

**Aceite:** amostra rotulada, before/after auditável, nenhuma afirmação sem fonte, rollback da política por versão e painel com explicação concisa do *porquê* e *o que falta*.

### Fase P3-R: Currículo real e kit de candidatura, sem depender de CV Builder externo

**Principal gargalo atual:** o repositório já seleciona frases do perfil para uma vaga, mas `build_support()` retorna `writes_cv=false` e não existe gerador PDF no snapshot. O blueprint P6 aguardava o Builder; isso NÃO deve bloquear o valor imediato do JOBOS.

**Fazer em dois níveis:**

**P3.1: Kit factual, sem browser automático (primeiro).**
1. Criar `src/jobos/matching/cv_packet.py` que recebe `job_id`, `job_version_id`, `profile_id` e análise atual e chama `matching.prepare.build_support()`.
2. Reusar exatamente fatos e textos de `master.json`, com `evidence_refs` e `qualifiers`, sem gerar afirmações novas.
3. Gerar `manifest.json`, `cv_data.json`, `answers.json` e `cv.html` imprimível (CSS @media print) em pasta privada `data/artifacts/...`.
4. Em `cv_data`, incluir seleção de headline, histórico profissional fiel, educação, skills classificadas por status real, projetos e contatos autorizados. Se não existir dado suficiente, marcar `MANUAL_REQUIRED`.
5. Preferir dois ou três layouts discretos de 1–2 páginas, otimizados para leitura humana e parsing ATS, sem CSS exótico ou textos em imagem.
6. Interface oferece **“Abrir currículo imprimível / Salvar como PDF”**; o usuário salva no Edge/Chrome. Não exigir instalação de Chromium ou Builder para esse primeiro aceite.
7. Manter vínculos de `artifact` no SQLite, hash SHA-256 e versão congelada do pacote. Reusar `artifacts` de `0001_init.sql` e `GET /api/artifacts/...`; criar migração `0003_*` apenas se metadados adicionais forem estritamente necessários.
8. Validar PDF exportado manualmente: texto selecionável, dados completos, paginação, cabeçalho, links, datas e qualificadores; sem claim não suportada.

**P3.2: Export PDF automatizado (depois).**
1. Se Edge estiver disponível, experimentar Playwright com `channel=msedge` e template HTML local; verificar compatibilidade e uso de RAM.
2. Se houver bloqueio de renderização, manter fluxo manual como fallback plenamente funcional.
3. Opcionalmente integrar CV Builder real **após fornecer código, esquema JSON e fixture**, sem supor métodos como `window.loadCV()`. A ausência do Builder não pode suspender o JOBOS.

**Arquivos existentes a estender:** `matching/prepare.py`, `matching/profile.py`, `api/app.py`, `web/painel/src/preparo.ts`, `web/painel/painel.js`, `tests/test_prepare.py`.  
**Novos possíveis:** `matching/cv_packet.py`, `matching/cv_render.py`, `tests/test_cv_packet.py`, `web/painel/cv-print.css`.  
**Aceite:** duas vagas geram CVs honestamente diferentes, com evidência por linha; original `master.json` intacto; histórico de CV congelado e pacote recuperável.

### Fase P4-R: Autenticação e preenchimento ATS assistido

**Distinção obrigatória:** `collectors/totvs.py` lê listagens públicas; `applications/adapters/totvs.py` (novo) vai lidar com formulário autenticado. Não reutilizar o scraper como robô de candidatura.

**P4.0: Infra compartilhada.**
- Dependência opcional `ats` em `pyproject.toml`: Playwright Python, apenas nesta extra; não puxar no `pip install -e .` padrão. Fazer lock dedicado ou estratégia de lock testada com `requirements.lock` existente.
- `applications/browser/session_manager.py`: `launch_persistent_context` visível, com `user_data_dir` dedicado **por provedor ou tenant** em pasta privada ignorada pelo Git. Nunca usar perfil principal do Chrome como diretório automatizado.
- `applications/browser/auth_handoff.py`: abrir login, detectar `AUTH_REQUIRED`/`AUTH_WAITING_HUMAN`/`AUTHENTICATED`/`AUTH_EXPIRED`/`AUTH_BLOCKED`. Rafael digita senha e Authenticator diretamente no site; script nunca coleta nem registra segredo.
- `applications/browser/form_inspector.py`: encontrar campos por label/role/name/autocomplete e relacionamento com descrições; classificar `text/select/radio/file/checkbox/consent/test/captcha`, required e tipo da pergunta; sem coordenadas fixas nem XPath absoluto frágil.
- `applications/answer_bank.py`: resolver perguntas **somente** de perfil validado, respostas pré-aprovadas ou defaults seguros documentados. `salary`, `PCD`, raça, gênero, autorização, disponibilidade, relocation e certificações sensíveis devem exigir decisão humana se não houver resposta explícita.
- `applications/orchestrator.py`: preparar, inspecionar, preencher e parar em `awaiting_review`. Execução repetida é idempotente; toda tentativa tem `attempt_id` e versionamento de selectors.

**P4.1: Fixture local primeiro.**
- Criar HTMLs locais para formulário com upload, multietapas, validação, checkbox de consentimento, erros e versão alterada.
- Testar sem internet, senha ou conta; botão final bloqueado pela guarda de submissão.
- O sistema deve recusar seletor ambíguo, field desconhecido, documento não encontrado e resposta sem evidência.

**P4.2: TOTVS inicial.**
- Primeiro abrir vaga da Bram Offshore pela URL obtida do coletor, conferir domínio e ID.
- Inspecionar modalidades de candidatura normal/simplificada sem extrapolar experiência de um tenant para todos.
- Login Google/Authenticator é sempre handoff humano e pode falhar em ambiente automatizado; respeitar bloqueio.
- Após sessão válida, preencher campos conhecidos e anexar o CV **já aprovado**; parar antes de enviar. Não capturar cookies/tokens em logs ou snapshots.
- Executar 10 fixtures de layout e **um dry-run visual real, sem envio**, com revisão do Rafael.

**P4.3: Gupy em versão separada.**
- Gupy padrão, rápida e fluxos de etapas/avaliações são variantes diferentes.
- Perfil compartilhado entre candidaturas: não sobrescrever dados globais ao otimizar uma vaga específica sem revisão explícita do Rafael.
- Autenticação, consentimento, perguntas eliminatórias e questionários ficam manuais quando não previamente autorizados.
- Evitar operações massivas e formulários enviados em loop.

**P4.4: SAP SuccessFactors.**
- Sessões por tenant/empresa; URL validada e whitelisted.
- Fluxo “Quick Apply” separado de cadastro completo e múltiplas telas, upload e autenticação.
- Se houver 2FA, testes seletivos ou alteração de formulário, pausa segura.

**Fallback SSO:**
- Se o login Google recusar a sessão Playwright, não contornar proteção ou detecção; deixar o Rafael entrar no navegador normal e, **somente depois de sua aprovação**, avaliar extensão Chrome MV3 local com permissões restritas e conteúdo não sensível. Não implementar extensão até ser necessária.
- Não tentar automatizar CAPTCHA, MFA, perfis de empregador ou endpoints privados.

**Aceite P4:** dry-run com 100% dos campos preenchidos corretos e rastreáveis em fixture, um fluxo visível com login humano, nenhum envio involuntário, cookies guardados apenas no armazenamento privado do navegador, sem segredo nos logs.

### Fase P5-R: Prova, estados, retries e prevenção de candidatura fantasma

O modelo de estados JÁ existe em `domain/states.py` e `applications/service.py`. Reusar `discovered`, `shortlisted`, `cv_draft`, `cv_ready`, `awaiting_review`, `submission_unknown`, `submitted_manual`, `submitted_verified`, `dismissed`, `legacy_needs_review`. Não substituir por nova máquina de estados incompatível.

**Implementar:**
1. Novo armazenamento de `application_attempt`/`submission_evidence`, por migração aditiva versionada, contendo `attempt_id`, `job_id`, `application_id`, `adapter_id`, `adapter_version`, `job_version`, `artifact_sha256`, `started_at`, `last_step`, `approval_at`, `confirmation_source`, `confirmation_id`, `status`.
2. Evento `awaiting_review` exige preview de respostas e CV selecionado; envio final exige ação separada e explícita do Rafael. No MVP, preferir que ele clique Enviar na plataforma.
3. Pós-envio: registrar somente evidência confiável: tela com ID da candidatura, dashboard do candidato vinculado ao anúncio ou confirmação claramente identificada. Não guardar captura com documentos pessoais se não for indispensável; texto/hashes saneados são preferíveis.
4. Timeout depois do possível envio = `submission_unknown`, jamais retry de clique por suposição. Consultar status oficial e oferecer reconciliação humana.
5. `submitted_verified` só quando `origin=platform_confirmation` com prova verificável; manter `submitted_manual` separado de “comprovado”.
6. Reuso de `application_events` e serviço `transition`, não gravar `prep_state` diretamente em endpoint.
7. Nunca mudar 13 antigas `auto_sugerida` para enviadas porque há CV ou sugestão; reconciliação das 15 manuais depende do estado factual atual do SQLite.

**Aceite:** testes de timeout após clique, reinício no meio do formulário, duplicata, ID ambíguo, tela de sucesso falsa, upload parcial e 2FA expirada. Nenhum teste produz `submitted_verified` sem origem/prova.

### Fase P6-R: Integração no painel e operação leve no Windows

**Não construir outro dashboard React ou framework pesado.** O painel atual tem `web/painel/painel.js` (vanilla JS), `painel.css` e preparo TS compilado. Reusar UI, porta 8776 e endpoints.

Adicionar ao detalhe de vaga:
- `Aderência`: nota por evidência, cobertura, gaps e preferências.
- `Preparar CV`: revisão das frases, qualificadores e pacote imutável.
- `Candidatura`: estado, último passo, abrir/reconectar sessão, revisar formulário, pausar/retomar.
- `Comprovante`: enviado afirmado pelo usuário versus verificado pela plataforma.
- `Fonte`: saúde, status de detalhamento e atualização.
- `Pendências`: lista curta “precisa de login”, “campo desconhecido”, “CV para revisar”, “vaga fechou”.

A API já dispõe de `GET /api/jobs/{id}`, `GET /api/applications`, `POST /api/applications/{job_id}/events`, `GET /api/artifacts/{id}/download`; criar rotas de CV/ATS usando contratos Pydantic e controles de origem existentes.

Desempenho para i5-10210U/8 GB/MX110:
- Não carregar modelo de IA, Windows subsystem Linux nem containers.
- Um navegador visível e um formulário por vez; fechamento robusto sem processos órfãos.
- Coleta HTTP já paraleliza 4 fontes; medir RAM/tempo antes de reduzir.
- Não deixar browser autenticado aberto 24/7 se não necessário; nunca guardar credencial em YAML, Git, logs ou frontend.
- Agendador existente às 08h, 12h, 14h, 18h continua para descoberta. Login/2FA e aplicação assistida são acionados pelo Rafael no painel.
- Pré-computar score quando vaga muda; UI consulta cache SQLite. Não recalcular centenas de vagas em cada render.
- Preservar margem de disco (~33 GB livres reportados em 23/10; reconfirmar), limpar somente previews temporários conforme política de retenção, nunca backups/artifacts sem revisão.

**Aceite:** fluxo ponta a ponta no painel existente sem travar coleta, sem CORS público, sem expor `_system` ou `data` e sem depender de IA/SMTP.

### Fase P7-R: Piloto e melhoria contínua

1. Primeiro obter 8–12 vagas realmente abertas e aderentes, com datas e IDs verificados.
2. Selecionar 3 boas vagas para preparo de CV e classificação humana.
3. Dry-run de formulário em TOTVS, Gupy e SAP só após a plataforma anterior passar nos testes.
4. Realizar **uma candidatura verdadeira por vez**, após autorização do Rafael; reconciliar status e comprovante.
5. Medir acerto das recomendações, minutos poupados, erros por ATS, número de interrupções para MFA, vagas que fecharam, duplicatas evitadas, convites para entrevista.
6. Reavaliar as regras de ranking com os erros reais. Em cada modificação, incrementar `policy_version` e manter análise antiga para comparação.
7. Criar pacote de regressão de HTML de ATS: cada mudança de tela exige nova fixture e teste antes de retomar preenchimentos.
8. Atualizar `docs/PROGRESS.md` com status e resultado factual antes de fechar sessão.

**A condição de vitória não é “100 candidaturas automáticas”.** É receber boas oportunidades, candidatar com precisão e conseguir entrevistas sem esgotar tempo ou memória do PC.

---

## 6. Mapa de alterações por arquivo, respeitando a base existente

| Arquivo/pasta | Ação permitida | Motivo |
|---|---|---|
| `CLAUDE.md` | Atualizar com decisão `CORE ZERO-AI` e ordem atualizada | Todo agente futuro segue o mesmo contrato |
| `docs/PROGRESS.md` | Sempre atualizar após teste, com comandos e resultados | SSOT operacional |
| `docs/DECISIONS.md` | Acrescentar decisões, não apagar histórico | Porta/documentação, CV fallback, ATS human-first |
| `docs/SOURCE-COVERAGE.md` | Gerar atualização a partir de YAML e DB | Eliminar drift entre fontes e relatório |
| `config/app.yaml` | Manter porta 8776; ajustes somente após medição | Compatibilidade com outros apps do PC |
| `config/matching.yaml` | Preservar `ai.enabled=false`; versionar mudanças em `matching-v6` | Independência de IA e score auditável |
| `config/sources.yaml` | Correções pontuais após verificar site/tenant | Evitar quebrar coletores que funcionam |
| `src/jobos/collectors/*` | Não reescrever; corrigir fontes com fixtures | Coletores existentes já têm contrato |
| `src/jobos/matching/prepare.py` | Estender seleção factual, sem introduzir LLM | Base do CV |
| `src/jobos/matching/cv_packet.py` (novo) | Criar pacote JSON/HTML por vaga e hashes | P3 |
| `src/jobos/applications/service.py` | Reusar transições e evidência, sem redirecionar estados | P5 |
| `src/jobos/applications/browser/*` (novo) | Sessões Playwright e inspeção segura | P4 |
| `src/jobos/applications/adapters/*` (novo) | Adaptadores TOTVS, Gupy, SuccessFactors | P4 |
| `src/jobos/storage/migrations/0003_*.sql` (se preciso) | Adicionar tabelas de tentativas/provas sem destruir as anteriores | P5 |
| `src/jobos/api/app.py` | Rotas pequenas, compatíveis e testadas | P3/P4/P5 |
| `web/painel/src/preparo.ts` e `preparo.js` | TS é fonte; JS é compilado | P3, nunca editar output sozinho |
| `web/painel/painel.js` / CSS | Evoluir 8 seções existentes | P6 |
| `scripts/windows/*` | Reusar, corrigir somente se diagnóstico falhar | Agendamento já implantado |
| `tests/*` | Tests unitários, fixtures HTML de ATS e integração | Não quebrar 141 testes relatados |
| `requirements.lock` / `pyproject.toml` | Playwright na extra opcional `ats`, após testar instalação | Core continua leve |
| `exports/portal.py` | Preservar projeção apenas pública | Privacidade e segurança |
| `config/profile/master.json` / `data/jobos.sqlite3` | Não tocar cegamente; dados locais não versionados no Git | Fatos pessoais e estado são do Rafael |

Regra adicional: nenhuma IA deve ser usada como “fallback” de campos desconhecidos em ATS. Um campo que o adaptador não entendeu fica para revisão humana.

---

## 7. Contratos novos mínimos, sem duplicar o que já existe

### 7.1 Contrato de adaptador de aplicação

```python
class ATSApplicationAdapter(Protocol):
    platform: str
    version: str

    def identify(self, url: str) -> bool: ...
    def inspect(self, page) -> "FormInspection": ...
    def auth_state(self, page) -> "AuthState": ...
    def fill_draft(self, page, answers: "ApprovedAnswers") -> "DraftResult": ...
    def find_confirmation(self, page) -> "ConfirmationEvidence | None": ...
```

O adaptador nunca recebe senha, token, código OTP ou autorização genérica para enviar. Deve fornecer versão, domínios permitidos, suporte a upload, etapas e razão de pausa.

### 7.2 Contrato de respostas factuais

```json
{
  "question_key": "years_maritime_ops",
  "answer": "valor aprovado pelo usuário ou extraído de período comprovado",
  "source": "profile",
  "evidence_refs": ["/experience_nodes/..."],
  "qualifiers": [],
  "approval": "preapproved",
  "updated_at": "ISO-8601"
}
```

O JSON é ilustrativo; o esquema real deve ser fechado só após auditar o perfil local. Campo sem evidência fica `MANUAL_REQUIRED`. Evitar replicar dados pessoais além do estritamente necessário.

### 7.3 Contrato do pacote de CV

```json
{
  "schema_version": 1,
  "job_id": "id canonico",
  "job_version_id": "versao da vaga",
  "profile_id": "versao do perfil",
  "policy_version": "matching-v6",
  "uses_ai": false,
  "claims": [
    {
      "text": "frase existente e revisada",
      "evidence_refs": ["/experience_nodes/..."],
      "status": "met"
    }
  ],
  "artifacts": {
    "html": "path relativo privado",
    "pdf": "opcional quando revisado",
    "sha256": "hash efetivo do pacote"
  }
}
```

As strings são exemplos de interface, **não fatos** sobre Rafael.

### 7.4 Estados e commit de evidência

- **Draft pronto:** `cv_ready` depois de revisão do pacote e hash.
- **Formulário preenchido:** `awaiting_review`; sem envio.
- **Possivelmente enviado, sem confirmação:** `submission_unknown`; interromper retries de envio.
- **Usuário confirma:** `submitted_manual` + `user_asserted`.
- **Plataforma prova:** `submitted_verified` + `platform_confirmation` + referência verificável.
- Aplicação e anúncio possuem estados independentes: anúncio fechado não apaga a história da candidatura.

---

## 8. Matriz de testes e aceites que faltam

| ID | Teste / cenário | Resultado obrigatório | Fase |
|---|---|---|---|
| Z01 | Instalação normal do core sem Playwright/IA | Coleta, score, API e painel funcionam | P0 |
| Z02 | Task Scheduler acionado e app aberto junto | Um ciclo ativo, outro pula sem corromper banco | P0 |
| Z03 | Fim de coleta parcial/falha/0 itens incompletos | Não fecha anúncios | P1 |
| Z04 | Fonte de escopo filtrado não vê anúncio antigo | Não confirma ausência fora do escopo | P1 |
| Z05 | Reuso da mesma vaga em outra fonte | IDs e relações preservados, sem candidatura duplicada | P1 |
| Z06 | Requisito PMP “certificação válida” não presente | Não declarar atendido por elegibilidade futura | P2 |
| Z07 | Ferramenta em desenvolvimento/projeto pessoal | Não promover para competência corporativa comprovada | P2 |
| Z08 | Local desconhecido e vaga remota | Rótulos honestos, sem hard reject indevido | P2 |
| Z09 | Duas vagas diferentes e mesmo perfil | CVs diferentes por seleção de fatos, sem alterar `master.json` | P3 |
| Z10 | Render HTML com campos longos e PDFs de 1–2 páginas | Sem corte, texto selecionável, hash e versão corretos | P3 |
| Z11 | CV refeito após candidatura existente | Não altera arquivo histórico associado | P3 |
| Z12 | TOTVS login Google e Authenticator | Pausa para humano, nenhum segredo em logs | P4 |
| Z13 | Campo desconhecido, CAPTCHA, consentimento | `MANUAL_REQUIRED`, sem resposta inventada | P4 |
| Z14 | Formulário muda label/DOM/ordem | Falha fechada, evidência de mudança e fixture nova | P4 |
| Z15 | Duas abas, duas tentativas e sessão expirada | Uma aplicação por vez, idempotência, sem sobrescrever perfil | P4 |
| Z16 | Upload falha ou currículo não é o aprovado | Não disponibiliza botão final no JOBOS | P4 |
| Z17 | Timeout após possível envio | `submission_unknown`, sem retry de envio | P5 |
| Z18 | Clicar “aplicada” sem confirmação de plataforma | Só `submitted_manual`, nunca `submitted_verified` | P5 |
| Z19 | Abrir artifacts por `../../`/absolute path | 404/403, nenhum dado privado exposto | P5 |
| Z20 | Site/portal reexportado | Apenas dados públicos; nenhum CV, sessão ou candidatura | P6 |
| Z21 | Sem internet, sem SMTP, sem IA | Histórico, fila, painel e revisão local continuam | P6 |
| Z22 | Sem Browser nem dependência ATS instalada | Coleta automática continua rodando | P6 |
| Z23 | Piloto em 3 vagas | Procedência, CV, formulário, evidência e tempo medidos | P7 |

Os testes existentes `tests/test_api.py`, `test_operations.py`, `test_matching.py`, `test_prepare.py` e `test_persistence.py` são a base; acrescentar casos sem recriar fixtures e não enfraquecer invariantes para que o teste “passe”.

---

## 9. Execução no Windows do Rafael, sem invadir outros projetos

Todos os comandos abaixo são para rodar **no PC do Rafael**, não foram executados nesta sessão.

```powershell
Set-Location -LiteralPath 'D:\dev\_dev web\_rvalle-site\__VAGAS\_system'
$Py = '.\.venv\Scripts\python.exe'

git status --short
& $Py -m jobos doctor
& $Py -m jobos status
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\show-status.ps1'
& $Py -m jobos cycle --dry-run --fixtures
& $Py -m pytest -p no:cacheprovider tests
```

**Antes de qualquer migração:** ler `git status`, comparar versão da venv e fazer `jobos backup --label pre-p6`. Não sobrescrever `data` nem restaurar backups por impulso.

**Interface existente:** `http://127.0.0.1:8776/painel/`.  
**Lançador:** duplo clique em `JOBOS.cmd` ou `scripts/windows/start-dashboard.ps1`.  
**Agendamento existente:** `JOBOS Local Engine`, horários 08h/12h/14h/18h BRT; verificar em `show-status.ps1`.  
**Não usar:** `python` genérico no PATH, `python -m http.server` servindo toda a raiz `__VAGAS`, porta 8765 (Correios) ou porta 8766 (WhatsApp Hub).

---

## 10. Prompt-mestre atualizado para Claude Code no projeto local

> Atue como engenheiro responsável pelo repositório EXISTENTE `apollorio/jobos`, clonado no Windows em `D:\dev\_dev web\_rvalle-site\__VAGAS\_system`. Leia primeiramente `CLAUDE.md`, `docs/PROGRESS.md`, `docs/DECISIONS.md`, `docs/AUDIT.md`, `pyproject.toml`, `config/*.yaml` e este roadmap AS-BUILT. NÃO recomece o produto: P0-P5, CLI, coletores, SQLite, matching-v6, API, painel, outbox e scheduler já foram implementados. Faça auditoria somente-leitura do `git status`, do banco e do agendador; diferencie snapshot remoto e mudanças locais não enviadas. Preservar todos os dados, aplicações legadas, backups, arquivos privados e alterações não commitadas.
>
> **Decisão de arquitetura definitiva: CORE ZERO-AI.** Nenhum LLM, embeddings, Ollama, Qwen, FastEmbed, PyTorch, serviço pago, Docker ou novo dashboard no MVP. Nenhuma AI deve ser instalada ou chamada implicitamente. A versão básica precisa rodar coleta, score, CV factual e candidatura assistida sem qualquer pacote de IA. Não converter competência pessoal em experiência profissional; respeitar `config/profile/master.json`, `truth_boundaries` e JSON Pointers.
>
> **Hardware:** i5-10210U, RAM 8 GB, MX110 2 GB, armazenamento ~33 GB livres no momento da declaração, Windows 64-bit. Usar Python 3.12 da `.\.venv\Scripts\python.exe` (o Python genérico é do Inkscape). Banco em WAL+NORMAL; servidor somente `127.0.0.1:8776`; preservar projetos nas portas 8765/8766 e Agendador `JOBOS Local Engine`.
>
> **Modo de trabalho:** (1) PLAN: evidências por arquivo/linha, funções já existentes, gaps e riscos; (2) IMPACT: mudanças previstas em DB, API, UI, scripts, legacy e privacidade; (3) APPROVAL: não iniciar mudanças de risco sem minha confirmação; (4) IMPLEMENT: um lote pequeno por vez, reutilizando contratos; (5) VERIFY: testes unitários, integração, fixture sem internet, dry-run real sem envio, lint/TS quando relevante; (6) REPORT: diff, resultados, comandos, ressalvas, PR/commit somente se autorizado. Nunca validar o próprio trabalho sem teste independente. Falhas não devem ser mascaradas.
>
> **Prioridade 1:** fechar P0-R com auditoria Windows/SQLite/scheduler e drift dos docs. **Prioridade 2:** ranking funcional e correção das fontes falhas. **Prioridade 3:** CV kit por vaga aproveitando `matching.prepare`, com HTML imprimível, manifesto de evidências e SHA, SEM bloquear no CV Builder não encontrado. **Prioridade 4:** adicionar Playwright em extra opcional `ats`, criar adaptadores de candidatura distintos dos coletores, começando por fixture local, depois TOTVS Google/Authenticator human-in-loop, Gupy e SAP SuccessFactors. O modo P7 inicial termina em `awaiting_review`, botão final de envio fora da automação. Não contornar MFA/CAPTCHA, não manipular perfil principal de Chrome, não registrar segredos. Estado `submitted_verified` só com prova da plataforma; `submission_unknown` não pode ser reaplicado cegamente.
>
> **Comece AGORA apenas com:** diagnóstico de arquivos/estado, `doctor`/`status`/`show-status.ps1` e testes existentes. Entregue tabela `JA_EXISTE / PARCIAL / FALTA / BLOQUEADO` com evidência, diferenças em relação ao commit `a85897cb39f5ade6ef67454216c064e8c65786ec` e primeiro patch proposto. Pare antes de mudanças de dados, envio externo ou dependências novas.

### Prompts curtos por etapa

**Após aprovar P0-R:**
> Faça somente correções verificadas de inconsistências e documentação. Não mude estados antigos por inferência, não reinstale tarefas sem motivo, não sobrescreva o banco. Atualize PROGRESS com outputs e datas; explique a divergência de 15/28 candidaturas antes de qualquer ação.

**Após aprovar P3-R:**
> Implemente kit de CV com `matching/prepare.py` existente, `master.json` privado e tabela `artifacts`, com seleção de fatos/rastreio de claims e HTML de impressão. Não fabrique textos de experiência. Dois anúncios geram pacotes diferentes, reproduzíveis, versionados, com teste e preview no painel. Não dependa do CV Builder externo.

**Após aprovar P4-R:**
> Construa primeiro um ATS fixture HTML local e uma extra de Playwright independente do core. Implemente inspeção, mapeamento determinístico e preenchimento, com humano em MFA, CAPTCHA, consentimentos, salário e envio. Nenhum submit real em teste. Só iniciar adaptador TOTVS depois que fixture e testes de idempotência/falha fechada passarem.

---

## 11. Ordem de implementação com critérios de liberação

| Onda | Trabalho | Pode começar? | Liberação |
|---|---|---|---|
| 0 | P0-R auditoria real do PC e reconciliação documental | Sim, somente leitura | Baseline e backup confirmados |
| 1 | P1-R fonte TechnipFMC e cobertura prioritária | Após baseline | Fixtures + sem falsos encerramentos |
| 2 | P2-R calibrar matching-v6 e UX das recomendações | Após baseline | Vagas rotuladas, métricas e versionamento |
| 3 | P3-R CV factual HTML/pacote por vaga | Após baseline e validação do perfil privado | 2 CVs revisados e artefatos imutáveis |
| 4 | P4-R fixture ATS sem conta | Após CV básico | Falha fechada e nenhuma submissão |
| 5 | P4-R TOTVS human-in-loop | Após fixture aprovada | Dry-run autenticado sem enviar |
| 6 | P4-R Gupy e SAP em ondas separadas | Após TOTVS estável | Variantes testadas, autorização por vaga |
| 7 | P5-R evidência/confirmado e P6-R UI | Em paralelo apenas se não disputarem schema | Estado íntegro, sem segredos e sem envio falso |
| 8 | P7-R piloto de candidaturas | Após end-to-end + aprovação do Rafael | Prova vinculada à vaga e histórico |
| Futuro | IA semântica/LLM, SMTP, WordPress, CV Builder específico | Não necessário | Novo pedido e plano separado |

**Roadmap anterior supersedido:** o documento `JOBOS-ROADMAP-COMPLETO (1).md` e `_blueprint/*` continuam como referências e históricos de desenho. Para tomada de decisão, prevalecem os **arquivos reais do repo, CLAUDE.md, DECISIONS.md, PROGRESS atualizado e este plano AS-BUILT**. Em caso de conflito, parar e documentar, jamais escolher silenciosamente.

---

## 12. Links diretos para rastreabilidade

- [Repositório JOBOS](https://github.com/apollorio/jobos)
- [README, instalação e comandos](https://github.com/apollorio/jobos/blob/main/README.md)
- [CLAUDE.md, regras técnicas](https://github.com/apollorio/jobos/blob/main/CLAUDE.md)
- [PROGRESS.md, status reportado](https://github.com/apollorio/jobos/blob/main/docs/PROGRESS.md)
- [DECISIONS.md, arquitetura aceita](https://github.com/apollorio/jobos/blob/main/docs/DECISIONS.md)
- [AUDIT.md, evidências do Windows e legado](https://github.com/apollorio/jobos/blob/main/docs/AUDIT.md)
- [config/sources.yaml, fontes atuais](https://github.com/apollorio/jobos/blob/main/config/sources.yaml)
- [config/app.yaml, 8776 e scheduler](https://github.com/apollorio/jobos/blob/main/config/app.yaml)
- [Matching-v6](https://github.com/apollorio/jobos/blob/main/src/jobos/matching/analyze.py)
- [Preparo sem IA](https://github.com/apollorio/jobos/blob/main/src/jobos/matching/prepare.py)
- [Estados de candidatura](https://github.com/apollorio/jobos/blob/main/src/jobos/domain/states.py)
- [Serviço de candidatura](https://github.com/apollorio/jobos/blob/main/src/jobos/applications/service.py)
- [API existente](https://github.com/apollorio/jobos/blob/main/src/jobos/api/app.py)
- [P6/P7 no blueprint original](https://github.com/apollorio/jobos/blob/main/_blueprint/01-ROADMAP.md)
- [Testes existentes](https://github.com/apollorio/jobos/tree/main/tests)

**Resultado esperado:** JOBOS independente, gratuito, recuperável e pequeno o bastante para o PC atual, aproveitando o motor que já foi construído. Uma fila de candidaturas com CV verdadeiro, apoio aos logins obrigatórios e evidência de envio, sem colocar IA entre a pessoa e o formulário.
