# Mapa de reaproveitamento (P0)

Legenda: **reutilizar** (lógica portada quase igual), **adaptar** (portada com correção de contrato), **substituir** (novo comportamento), **referência** (consultado, não executado), **desativar** (não roda no sistema novo).

O pacote legado se chama `jobos`, igual ao novo. Para evitar colisão de import, nada é importado de `Artifact/`; a lógica útil foi portada para `_system/src/jobos/collectors/` com a origem anotada no módulo.

## Python (`Artifact/`)

| Arquivo | Decisão | Destino / motivo |
|---|---|---|
| `run.py` | substituir | `jobos.cli` com argparse estrito, códigos 0/2/3/4/5 |
| `jobos/store.py` | substituir (dados migrados) | `storage/` + `persistence.py`; identidade forte, versões, datas separadas |
| `jobos/fontes.py` | adaptar | cadeia de estratégias vira adapter principal + fallback explícito no `sources.yaml` |
| `jobos/resilience.py` | adaptar | retry com backoff/jitter e `Retry-After` em `collectors/http.py`; memória de estratégia não é usada |
| `jobos/preflight.py` | adaptar | queda anômala (limiar 50%) vira bloqueio de inferência de ausência em `persistence.py` |
| `jobos/sources/gupy.py` | adaptar | `collectors/gupy.py` (`__NEXT_DATA__` + detalhe por ID) |
| `jobos/sources/totvs.py` | adaptar | `collectors/totvs.py` |
| `jobos/sources/web.py` | adaptar | J2W, inHire, DOF, Workable, Workday, vagas.com.br, Greenhouse; cortes de 6.000 caracteres removidos |
| `jobos/sources/ats.py` | adaptar | SmartRecruiters; demais adapters genéricos ficam como referência |
| `jobos/sources/adzuna.py` | referência | exige credencial; fora da primeira entrega |
| `jobos/score.py` | substituir | `matching/` determinístico com evidências; `interview_probability` descontinuada |
| `jobos/triage.py` | adaptar | listas de cidades viram política visível em `config/preferences.yaml` |
| `jobos/compat.py` | substituir | sem corte de 2.500 caracteres; requisitos por seção |
| `jobos/autoapply.py` | desativar | `consolidar_pendentes()` não existe no sistema novo; registros migram para revisão |
| `jobos/bulletin.py`, `digest.py` | adaptar | `notifications/render.py` (texto/HTML/.eml) + outbox; SMTP separado e desligado |
| `jobos/diff.py` | substituir | eventos `job.discovered`, `job.changed`, `job.missing`, `job.closed` |
| `jobos/sync.py`, `wordpress.py` | desativar | P8; exportação futura com completude por fonte |
| `jobos/probe.py` | referência | útil para descobrir ATS manualmente |
| `tools/truth_lint.py` | referência | heurística; validação de claims será por JSON Pointer (P6) |
| `tests/test_triage.py` | referência | casos de cidades/Greenhouse reaproveitados como ideia; testes que cristalizam rejeição oculta e candidatura presumida não são portados |
| `windows/*.ps1`, workflow GitHub | desativar | substituídos por `scripts/windows/*.ps1`; workflow nunca rodou |
| `config/companies.yml` | adaptar | importado para `config/sources.yaml` |
| `config/profile.yml` | adaptar | políticas para `config/preferences.yaml` com origem `legacy_profile_yml`; fatos ficam no `master.json` |
| `config/queries.yml` | adaptar | fonte `gupy-portal-queries` desativada |

## Portal (`__VAGAS/`)

| Arquivo | Decisão | Destino / motivo |
|---|---|---|
| `index.html`, `assets/jobos.js`, `jobos.css`, `inbox-swiipe-row.js`, `forms-google.js`, `img/` | reutilizar sem editar | servidos pela API local por allowlist; `jobs.json` e `assets/jobs-data.js` passam a ser gerados do SQLite em tempo de requisição |
| `assets/load-jobs.ts` | referência | coleta pura útil; leitores equivalentes portados para Python (decisão DEC-003) |
| `assets/merge-jobs.ts`, `update-jobs.ts` | desativar | fecham vagas na primeira ausência e gravam JSON paralelo |
| `assets/offer-page.ts` | referência | regras de "vaga encerrada"/JSON-LD inspiram verificação individual futura |
| `assets/rio.ts` | adaptar | listas viram preferência visível, sem bloqueio oculto |
| `assets/host.ts` | substituir | API FastAPI em 127.0.0.1 com allowlist |
| `assets/cache-logos.ts`, `forms-google.ts` | referência | não usados pelo engine |
| `sw.js`, `manifest.webmanifest` | reutilizar | servidos como estão; `/api/` já é ignorado pelo SW |
| `jobs.json`, `assets/jobs-data.js` | migrar | importados como snapshot histórico; depois são projeções |
| `design system/` | referência | não necessário ao painel |

## Plugin WordPress (`apollo-vagas/`)

Contrato futuro (P8), mantido intacto. Contrato observado: `vagas[]` sem versão de schema; `completo` do arquivo ignorado; fechamento por empresa ausente no lote. Exportação futura deverá emitir `completo` só por fonte integralmente varrida.
