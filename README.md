# JOBOS local

Sistema local que consulta as empresas cadastradas, detecta vagas novas e alteradas, compara requisitos com o perfil comprovado (`config/profile/master.json`) e registra candidaturas reais. Funciona sem Claude aberto, sem IA e sem SMTP.

## Início rápido

Dê duplo clique em `JOBOS.cmd`, na raiz de `_system`. O script sobe o servidor se ele estiver parado e abre `http://127.0.0.1:8776/painel/` numa janela de aplicativo, sem abas. Se o JOBOS já estiver no ar, só abre a janela. Fechar a janela do aplicativo deixa o servidor rodando. Para encerrar o servidor, feche a janela minimizada do Python.

O `index.html` do painel não abre pelo duplo clique: no disco ele mostra o aviso e para. O aplicativo é a página servida em loopback.

```powershell
Set-Location -LiteralPath 'D:\dev\_dev web\_rvalle-site\__VAGAS\_system'
powershell -NoProfile -ExecutionPolicy Bypass -File '.\scripts\windows\start-dashboard.ps1'
```

`-Browser` abre uma aba no navegador padrão. `-NoBrowser` só sobe o servidor. Painel operacional: `http://127.0.0.1:8776/painel/`. Portal antigo: `http://127.0.0.1:8776/`. A porta 8765 está ocupada por outro projeto neste PC.

## Comandos da CLI (todos verificados)

Sempre com o Python do projeto (`python` do PATH é o do Inkscape):

```powershell
$Py = '.\.venv\Scripts\python.exe'
& $Py -m jobos doctor                      # ambiente, banco, perfil, fontes, porta, bloqueios
& $Py -m jobos status                      # mesmo conteúdo de /api/status
& $Py -m jobos import-legacy --plan        # relatório, nada gravado
& $Py -m jobos import-legacy --apply       # idempotente; backup antes se o banco já tiver dados
& $Py -m jobos cycle --dry-run --fixtures  # offline, banco temporário, fixtures rotuladas
& $Py -m jobos cycle --dry-run             # rede só leitura, banco temporário
& $Py -m jobos cycle --mode manual         # ciclo real (coleta, análise, outbox em preview)
& $Py -m jobos collect --source prio-gupy [--dry-run]
& $Py -m jobos analyze --pending | --job <job_id>
& $Py -m jobos serve [--port 8776] [--no-worker]
& $Py -m jobos backup [--label nome]       # snapshot consistente + verificação de restauração
& $Py -m jobos notifications preview|list|retry [--dry-run]
& $Py -m jobos application list
& $Py -m jobos application confirm --job <id ou prefixo de 8+> --date AAAA-MM-DD [--note "..."]
& $Py -m jobos application set-state --job <id> --state shortlisted|dismissed|awaiting_review --reason "..."
& $Py -m jobos application stage --job <id> --stage interview [--reason "..."]
& $Py -m jobos import-browser-export --file marcas.json [--apply]
& $Py -m jobos export-portal [--out caminho]
& $Py -m pytest -p no:cacheprovider tests
```

Códigos de saída: 0 concluído, 2 parcial, 3 falha impeditiva (inclui flag desconhecida), 4 pulado por sobreposição, 5 configuração necessária.

## O que o sistema garante

- Histórico legado importado sem apagamento (`Artifact/jobs.db` aberto só em leitura); 28 registros "aplicados" antigos ficam em **Legado: revisar procedência**, fora do total enviado.
- Sugestão, e-mail, CV ou passagem do tempo nunca viram candidatura.
- Fonte com falha, parcial, filtro diferente ou queda anômala não encerra vaga.
- Datas de publicação, detecção e importação separadas; `~data` não vira publicação.
- Nota = aderência estimada por requisito com cobertura; não é chance de entrevista.
- Arquivos privados (`_system`, perfil, banco) nunca são servidos; API só em 127.0.0.1.

## Exportar marcações antigas do navegador

O portal antigo guarda "Aplicadas/Ocultas" no `localStorage` do navegador onde foi usado. Python não lê o navegador. Na página antiga, abra o console (F12) e execute:

```js
copy(JSON.stringify({"jobos-saved": localStorage.getItem("jobos-saved"), "jobos-muted": localStorage.getItem("jobos-muted"), "jobos-lifted": localStorage.getItem("jobos-lifted")}))
```

Cole em `marcas.json` e rode `import-browser-export --file marcas.json` (relatório) e depois com `--apply`.

## Limites atuais

Ver `docs/PROGRESS.md` (testado, bloqueado, próxima etapa). Resumo: SMTP desligado (preview em `data/outbox-preview`); CV Builder (P6) bloqueado por falta do código no disco; Oracle CE (ABS) sem leitor; análise é determinística por regras.
