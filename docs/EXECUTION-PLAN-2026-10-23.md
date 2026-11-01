# Plano de execução — JOBOS (23/10/2026)

## Emenda 30/10/2026

W2a entregou a sanitização dos requisitos (`matching-v7`, DEC-021). A calibração com rótulos não aconteceu. Ela fica como W2a-2 / `matching-v8` e depende de 30–50 vagas rotuladas pelo Rafael.

W4 (automação de navegador e envio) não começa. A DEC-022 não foi aceita. O caminho em uso é semi-automático: o JOBOS monta o currículo com ponteiros do perfil, a pessoa envia no próprio navegador e registra o comprovante. Gerar o currículo não envia a candidatura.

A tabela da seção 1 permanece como medição de 23/10. Não foi reescrita.

Fontes lidas: `CLAUDE.md`, `README.md`, `docs/*` (PROGRESS, DECISIONS, CONFLICTS), `_blueprint/00…09`,
`JOBOS-ROADMAP-COMPLETO (1).md` (P0–P9) e `JOBOS-OPEN-SOURCE-AI-AUTOAPPLY-ROADMAP-2026-10-23.md` (P0-R…P7-R, mais novo).
Regra de precedência adotada: o roadmap de 23/10 (as-built) prevalece sobre o completo onde divergem
(CV kit HTML antes do CV Builder; Playwright opcional; IA fora de todas as fases).

## 1. Linha de base medida agora (somente leitura)

| Item | Resultado real |
|---|---|
| `pytest -p no:cacheprovider tests` | 322 testes, exit 0 (PROGRESS ainda diz 141) |
| `jobos doctor` | tudo OK; `cv_builder` BLOQ (P6) |
| `jobos status` | 2.448 vagas (758 ativas, 187 ausentes não confirmadas, 184 encerradas, 1.319 desconhecidas) |
| Candidaturas | 13 `legacy_needs_review` + 15 `submitted_manual` (PROGRESS ainda diz 28 / 0) |
| Agendador `JOBOS Local Engine` | última 23/10 18:00, código 2 (parcial: TechnipFMC 422); próxima 24/10 08:00 |
| Fontes | 32 complete, 1 failed, 15 unconfigured, 1 never_run |
| `jobs.json` público | só campos públicos (título, local, URL, datas) — sem nota, CV, notas ou e-mail |

## 2. Auditoria de impacto

### Macro (afeta dados, operação ou segurança)

1. **Ciclos agendados 4×/dia no mesmo banco.** Qualquer migração (P5-R `0003_*`) ou mudança em `src/jobos`
   deve entrar entre ciclos (janela 18:05→07:55), com `jobos backup` antes e respeitando `data/cycle.lock`.
   Código novo fica em branch/worktree até verde; o Agendador importa `src/` direto.
2. **Projeção pública regravada a cada ciclo** (`jobs.json`, `assets/jobs-data.js`, DEC-017). Mudança no
   exportador vai para o site no próximo ciclo. P8 exige allowlist testada (T49) antes de qualquer campo novo.
3. **Envio externo e sessões logadas (P4-R/P7-R).** Conflita com `CLAUDE.md` ("envio externo desligado").
   Playwright com `user_data_dir` guarda cookies de ATS. Exige decisão explícita do Rafael, registrada em
   DECISIONS antes de qualquer código de navegador autenticado. Sem decisão, P4 para no fixture offline (P4.1-R).
4. **Mudança de política de análise** (P2-R → `matching-v7`) reclassifica todas as vagas; precisa de amostra
   rotulada (30–50 vagas pelo Rafael) e rollback por versão (DEC-015).
5. **Árvore do site contém dados privados** (`_system/data`, `.venv`, zips, `Artifact/jobs.db`). `.gitignore`
   não impede sincronização/HTTP; conferir RealTimeSync/exclusões antes de qualquer publicação.

### Micro (correções pontuais)

- PROGRESS defasado: contagem de testes, candidaturas (13+15) e "08:00 não confirmado" (o ciclo das 18:00 rodou).
- DEC-011 diz porta 8766; operação real é 8776 (WhatsApp Hub na 8766) → registrar DEC-020.
- `data/logs/jobos-YYYY-MM-DD.log` vazio enquanto `run-cycle-*.log` tem o conteúdo: logger duplicado/sem handler.
- Aviso Starlette: `httpx` no TestClient deprecado (sem efeito hoje).
- Testes sem evidência: T38 (caminho com espaço/cwd), T42 (HTML/instruções no anúncio), T43 (path traversal em
  `/api/artifacts/{id}/download`), T25 (perfil inválido mantém o último válido), códigos de saída 4 e 5.
- `doctor` não compara fuso do Windows com Brasília.
- `ri-*`/painel: sem tela "Arquivos" (bloqueada até existirem artefatos).

## 3. Ondas e distribuição de modelos

Critério: **Haiku** = mecânico (docs, YAML, testes de contrato simples); **Sonnet** = módulo único com
contrato claro; **Opus** = arquitetura, segurança, esquema, integração e revisão final de cada onda.
Toda entrega de agente mais barato passa por revisão/verificação do Opus antes de merge.

| Onda | Pacote | Modelo | Risco | Saída verificável |
|---|---|---|---|---|
| W0 | Backup `pre-p6`; reconciliar PROGRESS (13+15, 322 testes, ciclo 18:00); DEC-020 porta 8776 | Haiku | baixo | backup com restauração verificada; docs corretos |
| W1a | Testes T38, T42, T43, T25, saída 4/5; checagem de fuso no `doctor`; logger `jobos-*.log` | Haiku | baixo | +N testes verdes |
| W1b | P1-R: matriz de saúde das fontes no painel (`sources.yaml` + `source_runs`); diagnóstico TechnipFMC 422 | Sonnet | médio | seção no painel + teste da API |
| W1c | P3.1-R: `matching/cv_packet.py` + `cv_render.py` + `cv-print.css` → `data/artifacts/<job>/<ver>/` com SHA-256, T28/T29/T47 | Sonnet (Opus revisa claims) | médio | 2 vagas → CVs honestamente diferentes; `master.json` intacto |
| W2a | P2-R: dicionários YAML de sinônimos + calibração `matching-v7` após rótulos | Haiku (YAML) → Sonnet (calibração) | médio | precision@8 antes/depois; rollback por versão |
| W2b | P5-R: migração aditiva `0003` (`application_attempt`, `submission_evidence`), máquina de estados, `submission_unknown` sem retry | **Opus** | alto | testes timeout/reinício/duplicado/tela falsa |
| W2c | P6-R parcial: tela "Arquivos" + rotas Pydantic pequenas | Sonnet | médio | sem CORS; `_system/data` nunca servido |
| W3 | P4.0/4.1-R: infraestrutura ATS **offline** (fixtures HTML locais, `form_inspector`, `answer_bank`, guarda de envio) | **Opus** (design) + Sonnet (fixtures) | alto | 100% campos rastreáveis; botão final bloqueado |
| W4 | P4.2–4.4-R adapters reais (TOTVS → Gupy → SuccessFactors) e P7-R piloto | Opus + Rafael | crítico | **somente após decisão DEC sobre envio/cookies** |
| — | P8 exportadores com allowlist + contrato WordPress (sem push) | Sonnet | médio | T49 |
| — | P9 calibração com uso real (1 semana) | Rafael + Opus | processo | relatório semanal |

Paralelismo seguro: W1a, W1b e W1c tocam arquivos diferentes (tests/ + doctor; painel fontes; matching/cv_*).
W2b não roda em paralelo com nada que mexa em `persistence`/migrações.

## 4. Dependências humanas (não automatizáveis)

1. Revisar as 13 candidaturas legadas no painel.
2. URL correta de carreiras da TechnipFMC.
3. Rotular 30–50 vagas para P2-R.
4. Decidir política de envio real e de cookies de ATS (bloqueia W4).
5. Logins/MFA digitados pelo próprio Rafael em qualquer ATS.

## 5. Gate de conclusão por onda

`pytest` completo verde · `doctor` sem regressão · `cycle --dry-run --fixtures` com hash do banco real inalterado ·
PROGRESS atualizado · nenhuma mudança fora dos arquivos do pacote.
