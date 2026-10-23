# JOBOS local

Engine: esta pasta `_system`. Workspace: `D:\dev\_dev web\_rvalle-site\__VAGAS`.
Leia `docs/PROGRESS.md` para retomar e `docs/DECISIONS.md` antes de mudar arquitetura.

Regras centrais:
- Reaproveite Python/portal existentes; não crie outro motor concorrente. Não importe o pacote legado `Artifact/jobos` (mesmo nome).
- SQLite (`data/jobos.sqlite3`, WAL) é autoridade do estado; `jobs.json`/`jobs-data.js` são projeções servidas pela API.
- `config/profile/master.json` é autoridade de carreira; respeite `truth_boundaries` e evidências (JSON Pointer).
- Sugestão, e-mail ou CV gerado nunca significa candidatura enviada. Envio só por `application confirm` (user_asserted) ou prova de plataforma.
- Fonte parcial/falha não fecha vaga; ausência exige leitura completa no mesmo escopo, 2 vezes, intervalo ≥ 6 h.
- Datas de publicação e detecção são distintas; instantes em UTC, interface em `America/Sao_Paulo`.
- `_system` e dados privados não são diretório estático; a API serve só allowlist em 127.0.0.1.
- Dry run usa banco temporário; não envia nem altera estado real. `--fixtures` exige `--dry-run`.
- Envio externo e WordPress desligados. Nunca use `python` genérico (é o do Inkscape neste PC): use `.venv\Scripts\python.exe`.
- D: tem fsync lento: mantenha WAL + `synchronous=NORMAL` e transações agrupadas.

Detalhes: `_blueprint/02-ARQUITETURA-CONTRATOS.md`. Critérios: `_blueprint/07-VALIDACAO-ACEITE.md`.
Atualize PROGRESS ao concluir uma unidade verificada e antes de interrupção.

Comandos (verificados):

```powershell
& '.\.venv\Scripts\python.exe' -m jobos doctor
& '.\.venv\Scripts\python.exe' -m jobos status
& '.\.venv\Scripts\python.exe' -m jobos cycle --dry-run --fixtures
& '.\.venv\Scripts\python.exe' -m pytest -p no:cacheprovider tests
```
