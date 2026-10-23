# Open source: o que aproveitar e o que validar

Consulta às páginas primárias dos projetos e documentação em 22/10/2026. A seleção abaixo é uma decisão arquitetural para ESTE projeto, não ranking universal nem auditoria completa dos repositórios. Não use contagem de estrelas, alegações de velocidade ou datas de atualização do texto sugerido como evidência sem verificar.

## 1. Decisão resumida

O melhor reaproveitamento inicial está nos anexos do Rafael: já possuem leitores corporativos, perfil, banco e interface. Não instalar cinco engines concorrentes. A fronteira de extensão é o adapter de fonte e os contratos comuns do JOBOS.

| Projeto | O que foi possível confirmar na página primária | Decisão para o JOBOS |
|---|---|---|
| [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) | Agrega vários portais, retorna DataFrame; instalação `python-jobspy`; licença MIT e Python >=3.10 declarados | Adapter complementar opcional após coleta por empresa estável |
| [GodsScion/Auto_job_applier_linkedIn](https://github.com/GodsScion/Auto_job_applier_linkedIn) | Projeto de candidatura LinkedIn, com perguntas e currículo; licença atual MIT; README registra mudança de licença em versões antigas | Não é base do engine nem adapter Gupy; fora do MVP |
| [BharathLakkoju/job-scraper](https://github.com/BharathLakkoju/job-scraper) | Pipeline declarado de coleta, currículo direcionado e tracker Sheets; licença MIT declarada | Referência de organização de pipeline e tracking; não substituir SQLite/local |
| [elchananvol/AIJobScraper](https://github.com/elchananvol/AIJobScraper) | Coleta, avaliação por modelo e organização em Excel | Referência conceitual; licença não localizada na página inspecionada, confirmar antes de copiar código |
| [deepakdevp/job-hunter](https://github.com/deepakdevp/job-hunter) | Pipeline declarado com descoberta, enriquecimento, score e currículo; licença MIT | Referência de decomposição e validação; não importar outro motor completo |

Essas páginas demonstram existência e propósito declarado. Não demonstram que uma candidatura real no ATS do Rafael funcionará, que todos os sites aceitam automação ou que os modelos não inventam fatos. Um README com “auto-apply” não é teste no seu ambiente.

## 2. Como incorporar JobSpy sem perder controle

1. Optional extra do projeto, instalado somente quando habilitado; não inflar dependências do primeiro ciclo.
2. Adapter produz o mesmo `SourceBatch` do resto do engine. Mapear campos e DataFrame para tipos JSON validados.
3. `None`, `NaN`, datas Pandas e timezone precisam ser normalizados, sem strings artificiais “nan”.
4. Separar fonte agregadora de fonte oficial; preservar URL original e link canônico quando realmente encontrado.
5. Queries de 72 horas são descoberta incremental. Não usar resultado para fechar vagas antigas.
6. Filtros por cargo, local, remoto e idade são configuração. Não copiar defaults de outro país sem verificar suporte atual.
7. Deduplicação usa referências fortes e possíveis relações, não só título/empresa.
8. Timeout, cap de resultados e cache. Bloqueio deve ficar visível; não tentar contornar CAPTCHA ou bloqueios com rotação de identidade.
9. Avaliar qualidade por vagas relevantes recuperadas, descrição disponível e saúde, não apenas contagem.
10. Testar um conjunto pequeno de consultas e conservar o engine funcional se JobSpy deixar de funcionar.

Não fazer `pip install -U` indiscriminado em cada agendamento. Instalar uma versão testada, registrar lock e atualizar em manutenção controlada.

## 3. Pequeno conjunto de componentes

| Necessidade | Escolha inicial | Motivo |
|---|---|---|
| HTTP | `requests` já usado | Reduzir mudanças e aproveitar sessões/fixtures |
| YAML | PyYAML já usado, com loader seguro | Configuração humana existente |
| Datas | `datetime`, `zoneinfo`, `tzdata` e parser já necessário | UTC interno e apresentação em Brasília |
| Banco | `sqlite3` padrão | Já existe histórico; backup e transações sem serviço extra |
| Modelos/contratos | Validação de tipos compatível com API escolhida | Evitar payloads ambíguos de coletores/IA |
| API local | FastAPI + Uvicorn, proposta a validar no ambiente | Backend pequeno junto do Python |
| Similaridade | RapidFuzz existente | Sugerir relações, nunca provar identidade sozinho |
| Browser/PDF | Playwright Python, fase de documentos/ATS | Mesmo conjunto para renderização e formulários assistidos |
| Lock Windows | Lock de SO ou biblioteca compatível testada | Evitar concorrência entre entradas |
| SMTP | `smtplib` ou transporte equivalente existente | Envio separado da renderização e persistência |
| IA local | Provider opcional, como serviço local já instalado | Não impor chave externa; qualidade depende de modelo/hardware |
| Qualidade | pytest/linters escolhidos conforme projeto | Verificar sem reconstruir uma infraestrutura de CI |

Nada exige instalar todas as dependências na primeira fase. Não substituir biblioteca apenas por gosto quando a existente atende ao contrato.

## 4. Processo de adoção de código externo

Registrar repositório, arquivo usado, licença daquela revisão, commit/tag real, dependências, mudanças locais e teste. Consultar a licença completa antes de copiar. Projeto público sem licença reconhecida não é automaticamente reutilizável.

Preferir dependência publicada com versão fixada e adapter estreito em vez de copiar um repositório inteiro. Se só uma ideia for útil, implementar a interface local sem incorporar código alheio desnecessário. Nunca trazer senhas/modelos de perfil de exemplos de terceiros.

Não assumir que licença de software autoriza qualquer uso de uma plataforma externa. Em especial, documentação pública de listagem não dá ao candidato credenciais de API do empregador.

## 5. Distinção crítica: ler vagas versus enviar candidatura

A documentação Job Board da Greenhouse informa GET público e exige autenticação para o endpoint de submissão. Não pressupor que Rafael tem uma chave de Job Board do empregador. Usar formulário público acessível, quando apropriado, no fluxo assistido.

Gupy e Workday precisam de descoberta separada das capacidades reais. Um endpoint observado no HTML ou pelo leitor legado não vira contrato oficial nem API geral de candidatura. Classificar adapter por `documented_api`, `observed_public_endpoint` ou `html_parser` e mostrar fragilidade esperada.

Na Gupy, a documentação consultada na etapa anterior desta conversa descreve propagação de alterações do currículo do perfil para candidaturas ativas e uma modalidade de Candidatura Rápida com currículo anexado. Confirmar o fluxo atual quando implementar. Não reescrever currículo global repetidamente como método de personalização por vaga.

## 6. Fontes primárias para implementação

| Tema | Fonte | Uso no plano |
|---|---|---|
| Memória de projeto Claude Code | [How Claude remembers your project](https://code.claude.com/docs/en/memory) | CLAUDE.md curto e documentos específicos consultáveis |
| Práticas Claude Code | [Best practices](https://code.claude.com/docs/en/best-practices) | Critérios verificáveis e cuidado com contexto |
| Agendador Windows | [Task Scheduler](https://learn.microsoft.com/en-us/windows/win32/taskschd/task-scheduler-start-page) | Execução por gatilhos no sistema operacional |
| Configurações da tarefa | [New-ScheduledTaskSettingsSet](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/new-scheduledtasksettingsset) | Recuperação, energia, limites e concorrência |
| SQLite Python | [sqlite3](https://docs.python.org/3/library/sqlite3.html) | Transações, leitura e backup consistente |
| SQLite WAL | [Write-Ahead Logging](https://sqlite.org/wal.html) | Banco local e limites de compartilhamento |
| API local | [FastAPI Static Files](https://fastapi.tiangolo.com/tutorial/static-files/) | Montar só diretórios públicos selecionados |
| Sessões de browser | [Playwright Authentication](https://playwright.dev/python/docs/auth) | Estado autenticado privado e separado |
| PDF | [Playwright Page API](https://playwright.dev/python/docs/api/class-page#page-pdf) | Exportação do documento renderizado |
| Greenhouse | [Job Board API](https://docs.greenhouse.io/job-board.html) | Diferenciar leitura pública de submissão autenticada |
| Gmail, se escolhido | [App passwords](https://support.google.com/accounts/answer/185833?hl=en) | Verificar disponibilidade e alternativas de autenticação |
| Gupy | [Atualizar currículo](https://suporte-candidatos.gupy.io/s/article/Como-atualizar-o-meu-curriculo?language=pt_BR) | Confirmar efeito global de mudanças no perfil |
| Gupy | [Candidatura Rápida](https://suporte-candidatos.gupy.io/s/article/como-funciona-a-ordenacao-das-candidaturas-em-vagas-de-candidatura-rapida?language=pt_BR) | Confirmar modalidade e campos atuais |

As páginas de suporte Gupy renderizaram um shell de erro CSS ao abrir nesta inspeção; trechos da busca e leitura da etapa anterior forneceram a informação geral. Isso reforça a necessidade de verificar o formulário real no momento da implementação. Não afirmar que o site foi testado autenticado.

## 7. Decisões que são propostas, não fatos de terceiros

Estrutura `_system`, nomes da CLI, esquema do banco, score com cobertura, fases, estados, testes e default de envio desativado são escolhas deste blueprint. Não são funcionalidades garantidas por JobSpy, Claude Code ou ATS. Claude deve implementá-las e mostrar evidência antes de afirmar prontidão.
