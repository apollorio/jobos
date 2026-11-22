# JOBOS local: scripts para Windows

Scripts em Windows PowerShell 5.1 para operar o engine local. Todos descobrem a raiz do engine pela
própria pasta (`scripts\windows\..\..`), usam sempre o Python do venv (`.venv\Scripts\python.exe`) e
repassam o código de saída do app. O `python` do PATH nunca é usado (neste PC ele aponta para o Inkscape).

Raiz do engine: `D:\dev\_dev web\_rvalle-site\__VAGAS\_system`

Os comandos abaixo supõem que o diretório atual é a raiz. De outro lugar, use o caminho completo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\dev\_dev web\_rvalle-site\__VAGAS\_system\scripts\windows\show-status.ps1"
```

Todos aceitam `-Root <pasta>` (precisa conter `pyproject.toml` e `src\jobos`).

## Códigos de saída

| Código | Significado |
| --- | --- |
| 0 | ok |
| 2 | parcial (algumas fontes falharam) |
| 3 | falha |
| 4 | ciclo pulado por sobreposição (outro ciclo em execução) |
| 5 | configuração necessária (venv ausente, porta ocupada, nome de tarefa recusado) |

## bootstrap.ps1: preparar o ambiente

Cria o `.venv` se faltar, instala o pacote e roda o `doctor`. Idempotente.

```powershell
# diagnóstico sem alterar nada (não instala, não cria, não roda o doctor)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\bootstrap.ps1" -CheckOnly

# preparar: venv (se faltar) + pip install -e ".[dev]" + doctor
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\bootstrap.ps1"

# recriar o venv (o antigo é renomeado para .venv.bak-<timestamp>, nunca apagado)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\bootstrap.ps1" -Recreate
```

- Python base: `py -3.12`; se o launcher falhar, tenta `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`.
- Se existir `requirements.lock`: `pip install -r requirements.lock` e depois `pip install --no-deps -e <raiz>`.
  Sem lock: `pip install -e "<raiz>[dev]"`.
- `-CheckOnly` sai com 0 (pronto) ou 5 (falta algo). Sem `-CheckOnly`, sai com o código do `doctor`.
- `-Recreate` recusa renomear se houver processo usando o `.venv` (não encerra nada).

## run-cycle.ps1: executar um ciclo

```powershell
# ciclo manual real
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\run-cycle.ps1"

# teste sem efeitos reais (banco temporário)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\run-cycle.ps1" -Mode manual -DryRun

# como o Agendador chama
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\run-cycle.ps1" -Mode scheduler

# sem enfileirar o resumo
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\run-cycle.ps1" -NoNotify
```

Log diário (horário local): `data\logs\run-cycle-AAAA-MM-DD.log`. Cada linha tem carimbo de data/hora
(momento da gravação, ao fim da execução), com marcadores `[INICIO]`, `[CMD]`, `[out]`, `[err]` e `[FIM]`.
A linha-resumo do app (`run_id=... status=... código=...`) aparece como `[out]`. Se o `.venv` não existe, o
script registra a linha de erro e sai com 5.

## start-dashboard.ps1: abrir o painel

O atalho de duplo clique é `JOBOS.cmd`, na raiz de `_system`. Ele chama este script.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-dashboard.ps1"

# aba comum, em vez da janela de aplicativo
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-dashboard.ps1" -Browser

# outra porta, sem abrir a janela
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\start-dashboard.ps1" -Port 8800 -NoBrowser
```

- Porta padrão: `server.port` do `config\app.yaml` (8776).
- Se a porta já responder `/api/health` com `jobos-local`, abre a janela e sai com 0. Não inicia outro servidor.
- Se a porta estiver em uso por outro processo, mostra nome e PID e sai com 5, sem encerrar nada.
- Sobe `python -m jobos serve --host 127.0.0.1 --port <porta>` na janela minimizada `JOBOS servidor`, espera até 20 s por
  `/api/health` e abre `http://127.0.0.1:<porta>/painel/` com Edge ou Chrome `--app`.
  Fechar a janela do aplicativo não encerra o servidor. Fechar a janela `JOBOS servidor` encerra.

## install-schedule.ps1: registrar o Agendador

Cria a tarefa única `JOBOS Local Engine` (pasta `\`) com 4 gatilhos diários (08:00, 12:00, 14:00, 18:00).

```powershell
# ver o plano sem alterar nada
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-schedule.ps1" -WhatIf

# registrar/atualizar a tarefa
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-schedule.ps1"

# registrar e desativar as duas tarefas legadas (sem remover)
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\install-schedule.ps1" -DisableLegacy
```

- Ação: `powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<raiz>\scripts\windows\run-cycle.ps1" -Mode scheduler`,
  com diretório de trabalho na raiz.
- Configurações: `StartWhenAvailable`, `MultipleInstances IgnoreNew`, limite de 50 min, roda na bateria.
- Conta: usuário atual, `LogonType Interactive`, `RunLevel Limited`. **Só executa enquanto o usuário estiver
  conectado (logado).**
- **PC desligado (ou suspenso) não executa tarefas e `WakeToRun` não está habilitado.** Com `StartWhenAvailable`,
  uma execução perdida roda quando o PC voltar e o usuário estiver conectado.
- Idempotente: se a tarefa existe, o XML atual é exportado para
  `data\backups\scheduler\<TaskName>-<timestamp>.xml` antes de atualizar.
- `-DisableLegacy` atua apenas em `jobos-vagas - ciclo 12h` e `jobos-vagas - ciclo 18h`: exporta o XML e usa
  `Disable-ScheduledTask` (nunca remove). Registro em `data\backups\scheduler\actions.log`.
  Nenhuma outra tarefa é tocada (nunca `RVALLE-Correios-Jobos-1530`).
- Avisa (sem alterar) se o fuso do Windows não for `E. South America Standard Time`.
- `-TaskName` e `-Times` permitem sobrescrever os valores do `app.yaml`; o nome precisa começar com `JOBOS`.

## remove-schedule.ps1: remover a tarefa

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\remove-schedule.ps1" -WhatIf
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\remove-schedule.ps1"
```

Exporta o XML para `data\backups\scheduler\` e remove somente a tarefa informada (padrão: nome do `app.yaml`).
Recusa nomes que não comecem com `JOBOS` e os nomes protegidos (legadas e `RVALLE-Correios-Jobos-1530`).
Para restaurar um backup: `Register-ScheduledTask -TaskName 'JOBOS Local Engine' -Xml (Get-Content -Raw -LiteralPath '<arquivo.xml>')`.

## show-status.ps1: ver o estado (somente leitura)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\show-status.ps1"
```

Seção 1, Agendador do Windows: Estado, última execução, último resultado (decimal e hexadecimal),
próxima execução, para `JOBOS Local Engine` e para as duas tarefas legadas (ou "NÃO ENCONTRADA").
Seção 2, Engine: saída de `python -m jobos status`. Quando a tarefa roda pelo `run-cycle.ps1`, o último
resultado do Agendador é o próprio código de saída do app (0, 2, 3, 4 ou 5).

## backup.ps1: backup do banco

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\backup.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\windows\backup.ps1" -Label antes-da-mudanca
```

Executa `python -m jobos backup --label <Label>` e repassa o código de saída.

## Observações

- A flag `--json` é global na CLI: use `.\.venv\Scripts\python.exe -m jobos --json status`
  (e não `status --json`).
- Arquivos `.ps1` e este `.md` estão em UTF-8 com BOM, para o PowerShell 5.1 ler os acentos corretamente.
- Os scripts definem `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8` e `JOBOS_ROOT=<raiz>` apenas para o processo
  deles (restaurados ao final) e fixam o diretório de trabalho na raiz.
