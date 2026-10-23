# Operação local: Windows, arquivos, agenda e e-mail

## 1. Modo de execução escolhido

Um processo de coleta executa um ciclo e termina. O Agendador do Windows inicia esse processo quatro vezes ao dia. O painel é outro processo local que pode ser aberto sob demanda; não precisa ficar aberto para coleta. O browser de candidatura assistida só é aberto quando solicitado em sessão interativa.

Não colocar `while True: sleep(...)` como agendador principal. Não depender de aba aberta, service worker, conversa de IA, terminal com `.venv` ativado ou WordPress recebendo visitas.

## 2. Bootstrap que Claude deve entregar

Proposta de scripts, todos sob `_system/scripts/windows`:

| Script | Comportamento exigido |
|---|---|
| `bootstrap.ps1` | Diagnosticar runtime, criar/reusar .venv, instalar lock, validar configuração local |
| `run-cycle.ps1` | Executar um ciclo com Python absoluto; propagar código de saída |
| `start-dashboard.ps1` | Iniciar API/painel em loopback, detectar porta ocupada e não matar processo alheio |
| `install-schedule.ps1` | Instalar/atualizar tarefa própria com quatro gatilhos |
| `show-status.ps1` | Mostrar tarefa Windows e estado do engine sem misturar ambos |
| `remove-schedule.ps1` | Remover somente a tarefa criada pelo projeto |
| `backup.ps1` | Acionar backup consistente via CLI |

O script resolve raiz pelo próprio caminho e permite override validado. Diretórios com espaços precisam de `-LiteralPath`, strings e argumentos corretos. Não construir comando por concatenação de entrada não confiável. Redirecionamento de log não pode esconder erro de processo nativo.

Preferir Python suportado e compatível, por exemplo 3.12 se já disponível. Não forçar instalação global de outra versão se a atual passa as verificações. Usar `python -m pip` do ambiente correto. `tzdata` costuma ser necessário para `zoneinfo` em Windows e deve ser testado.

Se Node/TS for necessário, usar dependências locais com lock e verificar execução do bridge em caminho com espaços. Não baixar runtime global sem necessidade.

## 3. Interface CLI a implementar

Estes comandos são o CONTRATO PROPOSTO, não estão todos presentes nos anexos. README final deve refletir os nomes implementados e os exemplos abaixo precisam ser atualizados se houver adaptação justificada.

```powershell
Set-Location -LiteralPath 'D:\dev\_dev web\_rvalle-site\__VAGAS\_system'
& '.\.venv\Scripts\python.exe' -m jobos doctor
& '.\.venv\Scripts\python.exe' -m jobos import-legacy --plan
& '.\.venv\Scripts\python.exe' -m jobos import-legacy --apply
& '.\.venv\Scripts\python.exe' -m jobos status
& '.\.venv\Scripts\python.exe' -m jobos cycle --dry-run --fixtures
& '.\.venv\Scripts\python.exe' -m jobos collect --source prio-gupy --dry-run
& '.\.venv\Scripts\python.exe' -m jobos cycle --mode manual
& '.\.venv\Scripts\python.exe' -m jobos serve --host 127.0.0.1 --port 8765
```

Semântica complementar:

- `doctor`: não corrige fatos silenciosamente; informa ambiente, caminhos, DB, fontes, serviços opcionais e ação necessária.
- `import-legacy --plan`: somente relatório. `--apply` é ação local autorizada, com backup e idempotência.
- `--dry-run`: rede somente de leitura quando aplicável; estado de negócio e filas reais permanecem inalterados. Usar DB temporário construído via backup API se necessário. Nunca usar `shutil.copyfile()` em DB ativo com WAL como garantia de consistência.
- `--fixtures`: execução offline reproduzível; deve ser inequívoca no painel/relatório, sem confundir fixture com vaga real.
- `cycle`: coleta, persiste, analisa conforme política, atualiza painel e enfileira resumo; envio depende de política separada habilitada.
- `serve`: não inicia scraper em cada refresh de página e não executa ciclo no import do módulo.
- `backup`: cria snapshot consistente, manifesto e verificação em cópia.
- `notifications preview`: gera HTML/texto/.eml sem envio.
- `notifications retry`: processa apenas mensagens configuradas/elegíveis; não presume exatamente uma entrega.
- `analyze --job <id>` e `cv build --job <id>`: ações locais por vaga com versões de entrada explícitas.
- `application confirm --job <id> --date <data>`: registro manual com procedência do usuário; não prova de plataforma.

## 4. Códigos de saída propostos

| Código | Significado | Conduta |
|---|---|---|
| 0 | Trabalho solicitado concluído | Exibir resumo; integrações desativadas não viram envio bem-sucedido |
| 2 | Concluído parcialmente | Preservar resultados bons e listar fontes/etapas com falha |
| 3 | Falha impeditiva | Diagnóstico e erro legível |
| 4 | Execução pulada por sobreposição | Sem novo scraper/boletim; mostrar proprietário da trava quando seguro |
| 5 | Configuração necessária para a ação solicitada | Ex.: envio pedido sem SMTP; coleta sem e-mail continua possível |

Esses números devem ser consistentes em CLI, PowerShell e observabilidade. Não capturar toda exceção e sair 0. Não provocar retentativa infinita do Windows para uma fonte permanentemente bloqueada. Scheduler pode ter política própria de retry limitada, ciente de códigos de saída.

## 5. Agenda do Windows

Configuração pretendida: uma tarefa `JOBOS Local Engine`, quatro gatilhos diários: 08:00, 12:00, 14:00, 18:00. Caminhos absolutos na ação e working directory em `_system`. A conta é a do usuário, com nível de privilégio mínimo necessário.

Microsoft oferece opções como `StartWhenAvailable`, `WakeToRun`, limite de execução e política de múltiplas instâncias. O comportamento real depende do Windows, energia, permissões e conta. Confirmar a configuração gerada e a execução real, não apenas que o registro da tarefa retornou sucesso.

Requisitos do instalador:

1. Verificar fuso do Windows (`Get-TimeZone`) e comparar com a intenção de Brasília. Gatilhos simples usam o relógio do PC. Não mudar o fuso do sistema sem instrução do usuário.
2. Capturar usuário e modo de logon. Uma tarefa configurada para sessão interativa não roda da mesma forma sem usuário logado. O modo inicial pode assumir sessão do Rafael ativa, mas isso precisa estar visível.
3. O coletor headless não pode abrir Playwright interativo em execução sem desktop. Browser assistido é ação separada.
4. Habilitar recuperação de horário perdido conforme suportado. Na volta do PC, coalescer execuções perdidas em uma coleta atual, em vez de quatro ciclos concorrentes e quatro e-mails repetidos.
5. Política `IgnoreNew` ou equivalente da tarefa, mais trava no engine. A tarefa não é a única forma de iniciar o processo.
6. Limite máximo de execução configurável e suficiente para fontes lentas, com marcação de interrupção. Não deixar processo órfão segurando lock para sempre.
7. Guardar XML exportado das tarefas JOBOS legadas antes de desativar uma comprovadamente substituída. Sem apagar tarefas de outros aplicativos ou projetos.
8. Não declarar que o PC desligado acordará. Wake depende de estados de suspensão/hardware/política; PC desligado não coleta.
9. `show-status` exibe último disparo/resultado do Agendador e último run completo/parcial da aplicação separadamente.

O agendamento pode ser instalado em modo coleta/preview sem e-mail real. Não bloquear coleta porque faltou senha SMTP.

## 6. SMTP: reduzir a opacidade

Manter transporte do legado como possibilidade, extraindo-o para provider de envio. Não gravar senha em `.ps1`, YAML versionado ou linha de comando. Fonte local de segredo pode ser Windows Credential Manager ou ambiente privado do processo/arquivo `.env` ignorado e excluído da publicação. O Agendador precisa conseguir resolver esse segredo na conta que executa; uma variável `$env:` aberta num terminal não configura automaticamente todas as sessões futuras.

Configuração mínima: host, porta, modo TLS, conta remetente, referência do segredo e destinatário do próprio usuário. Não adivinhar destinatário entre os endereços existentes no perfil e no script legado. A instalação inicial mantém destinatário não configurado e gera preview.

Se Gmail for escolhido, app password depende de disponibilidade na conta e verificação em duas etapas; OAuth também é opção. Não prometer que toda conta permite senha de app. Não pedir senha comum da conta.

Resumo sugerido:

```text
JOBOS: 3 vagas novas para revisar | 2 fontes com falha

Execução: 22/10 às 12h, Brasília
Cobertura: 26/28 fontes completas; 2 fontes indisponíveis

1. Empresa / cargo / local
   Por que combina: duas evidências objetivas
   Atenção: requisito obrigatório desconhecido
   Próxima ação: revisar descrição e preparar currículo
   Link: página oficial

Pendências: 2 currículos para revisar; 1 candidatura de procedência antiga
Diagnóstico: último sucesso de cada fonte no painel local
```

Os valores são exemplos de formato, não resultados atuais. Se o destinatário abrir e-mail no celular, um link `localhost` aponta para o próprio celular, não para o PC do Rafael. Incluir links oficiais das vagas; acesso remoto ao painel é uma fase separada.

Notificação sem vagas novas pode ser configurada como confirmação resumida diária, em vez de quatro e-mails vazios. Falhas relevantes entram no resumo, com dedupe para não repetir a mesma mensagem o dia todo. Não esconder falha atrás de “nenhuma vaga hoje”.

## 7. Backups e retenção

- Banco operacional em disco local, sem compartilhamento de escrita por rede.
- Backup via SQLite Backup API, com `integrity_check` na cópia e manifesto de hashes.
- Configurações, versão do perfil e artefatos referenciados precisam de backup além do DB.
- Backups automáticos antes de migrações e em política periódica configurável, por exemplo diário com retenção semanal/mensal proposta, sem apagar arquivos enviados ainda referenciados.
- Copiar somente snapshots consistentes para destino externo configurado. Não fazer espelhamento do `.db` ativo, `.wal` e `.shm` como estratégia de backup.
- Retenção de HTML bruto, logs e previews deve limitar crescimento. Nunca excluir provas de envio ou currículos associados a candidaturas por TTL genérico.
- Testar restauração em outro diretório e com HTTP/SMTP/WordPress desativados. Nunca testar restore diretamente sobre a base ativa.

## 8. Diagnóstico diário simples

1. Olhar horário da última execução e fontes que falharam.
2. Revisar três a cinco vagas prioritárias, sem meta de volume automático.
3. Conferir lacunas obrigatórias e currículo específico.
4. Registrar envio quando ele acontecer, com origem manual ou prova da plataforma.
5. Verificar follow-ups gerados por envios reais e evitar mensagens automáticas a recrutadores.

Relatório semanal: fontes com falha repetida, vagas úteis por empresa, tempo até revisar, currículos preparados e processos por estágio. Candidatura presumida do legado não entra no total comprovado. Não inferir eficácia causal a partir de poucas respostas.

## 9. Falhas e respostas esperadas

| Situação | Resposta |
|---|---|
| PC desligado | Nenhuma execução; recuperação ao voltar conforme tarefa; painel indica atraso |
| Rede caiu | Registrar fontes pendentes/falhas; preservar vagas e retentar dentro de limite |
| Layout do ATS mudou | `format_changed`, sem zerar ou encerrar histórico |
| Fonte retorna metade das páginas | `partial`, sem inferência por ausência |
| SMTP rejeita autenticação | Mensagem pendente de configuração; coleta/painel continuam |
| Timeout após SMTP possivelmente aceitar | `unknown`; evitar reenvio cego |
| Modelo local indisponível | Fallback determinístico ou análise pendente, método visível |
| JSON do perfil inválido | Último perfil válido permanece; erro visível |
| Usuário moveu a pasta | Doctor identifica caminhos; scripts resolvem raiz ou override explícito |
| Porta 8765 ocupada | Informar processo/alternativa sem encerrar processo alheio |
| Dois disparos simultâneos | Uma execução ativa, outra pulada e registrada |
| Sem código do CV Builder | Contrato bloqueado; coleta e painel seguem funcionando |
