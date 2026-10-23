# JOBOS: plano de execução local para Claude Code

Preparado em 22/10/2026. Idioma de trabalho: português do Brasil.

Raiz informada pelo Rafael:

```text
D:\dev\_dev web\_rvalle-site\__VAGAS
```

Raiz de implementação autorizada para o motor:

```text
D:\dev\_dev web\_rvalle-site\__VAGAS\_system
```

Este pacote contém especificações e prompts. Não contém um motor novo já instalado, não cadastra tarefas do Windows e não envia mensagens. Os comandos `python -m jobos ...` apresentados nos documentos são a interface que Claude deve implementar e verificar. Não são comandos que os anexos antigos já oferecem.

## A decisão principal

Consolidar o Python que JÁ EXISTE em `Artifact.zip`, aproveitar o portal de `web-vagas(1).zip`, escolher um leitor principal por fonte e transformar o SQLite local na autoridade do estado operacional. O WordPress fica como integração posterior. Não construir um terceiro sistema independente.

O objetivo inicial é um produto utilizável: histórico preservado, coleta com erros visíveis, painel local, classificação explicável e notificações em rascunho. Depois vêm agendamento, e-mail configurado, currículo por vaga e preenchimento assistido.

## Como entregar isso ao Claude Code

1. Salve `JOBOS-ENGINE-BLUEPRINT.zip` na pasta `__VAGAS` indicada acima.
2. Extraia o ZIP para `_system\_blueprint`. Os documentos numerados devem ficar diretamente nessa pasta.
3. Abra Claude Code na pasta `__VAGAS`.
4. Cole o conteúdo de `04-PROMPT-MESTRE-CLAUDE-CODE.md`.
5. Claude deve inspecionar o disco real, registrar o diagnóstico e começar a implementar P0 a P3. Não deve apenas responder com outro plano.
6. Em uma nova sessão, use o prompt de retomada de `05-PROMPTS-POR-FASE.md`. O progresso fica no disco, sem depender da memória da conversa.

Extração opcional pelo PowerShell, depois de salvar o ZIP exatamente no local acima:

```powershell
$JobosWorkspace = 'D:\dev\_dev web\_rvalle-site\__VAGAS'
$JobosBlueprint = Join-Path $JobosWorkspace '_system\_blueprint'
$JobosArchive = Join-Path $JobosWorkspace 'JOBOS-ENGINE-BLUEPRINT.zip'
if (-not (Test-Path -LiteralPath $JobosArchive -PathType Leaf)) {
    throw "Salve JOBOS-ENGINE-BLUEPRINT.zip em $JobosWorkspace antes de continuar."
}
if (Test-Path -LiteralPath $JobosBlueprint) {
    throw 'A pasta _system\_blueprint já existe. Use outra pasta para comparar versões sem sobrescrever seus documentos.'
}
New-Item -ItemType Directory -Path $JobosBlueprint | Out-Null
Expand-Archive -LiteralPath $JobosArchive -DestinationPath $JobosBlueprint
Set-Location -LiteralPath $JobosWorkspace
claude
```

Este trecho somente extrai documentos e abre Claude Code, se `claude` já estiver instalado e no PATH. Não instala o engine e não altera tarefas existentes.

## Ordem de leitura

| Documento | Uso |
|---|---|
| `01-ROADMAP.md` | Fases, dependências, entregas e critérios de conclusão |
| `02-ARQUITETURA-CONTRATOS.md` | Autoridade dos dados, diretórios, modelos, estados, API e integração |
| `03-AUDITORIA-ANEXOS.md` | O que realmente existe e os problemas encontrados |
| `04-PROMPT-MESTRE-CLAUDE-CODE.md` | Prompt completo para iniciar a implementação |
| `05-PROMPTS-POR-FASE.md` | Prompts de continuação focados por etapa |
| `06-OPERACAO-WINDOWS.md` | Inicialização, agendamento, e-mail, backup e manutenção |
| `07-VALIDACAO-ACEITE.md` | Casos de teste e definição objetiva de pronto |
| `08-OPEN-SOURCE-REFERENCIAS.md` | Seleção de bibliotecas, avaliação dos cinco repositórios e fontes |
| `09-DECISOES-E-CHECKPOINTS.md` | Modelos de decisões, registro de progresso e pendências |
| `10-INVENTARIO-ANEXOS.json` | Inventário com hashes e métricas obtidas dos anexos |

## Resultado esperado da primeira entrega

- Engine Python dentro de `_system`, executado por ambiente virtual próprio.
- Importação preservando o banco legado e as vagas JSON sem disparar alertas históricos.
- Remoção da conversão automática de sugestão em candidatura.
- Uma coleta completa com resultado individual por empresa e proteção contra fechamento indevido.
- Painel no endereço local proposto `http://127.0.0.1:8765`, se a porta estiver livre.
- Rastreamento de currículo, candidaturas, pendências e eventos em uma única base.
- Nenhum envio externo, candidatura ou publicação no WordPress durante testes.

## O que não deve atrasar essa entrega

Chave de IA, configuração de SMTP, conta de ATS, implementação do CV Builder, hospedagem e WordPress não são dependências de P0 a P3. Deve existir classificação determinística inicial e preview de notificações sem rede de envio.

Os horários finais são 08:00, 12:00, 14:00 e 18:00 em `America/Sao_Paulo`. Esta especificação interpreta 12h como meio-dia.

## Uma observação sobre o seu diretório

`_system` ficará dentro de uma árvore que também contém arquivos de site. Isso NÃO o torna publicável. Banco, perfil completo, logs, cookies e credenciais precisam ficar excluídos de qualquer servidor estático e sincronização de publicação. `.gitignore` sozinho não resolve acesso HTTP nem regras de RealTimeSync.
