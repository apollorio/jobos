# Validação e definição de pronto

## Princípio

Teste existe para evitar perda de histórico, candidatura inventada, encerramento indevido, currículo incorreto e execução silenciosamente quebrada. Não escrever testes que apenas repetem cada linha da implementação. Reaproveitar as fixtures e testes legados quando verificarem o comportamento correto.

Fixture sintética deve estar rotulada como teste. Resultado de fixture não pode aparecer no painel de produção como vaga observada. Smoke test de um portal prova somente aquele fluxo naquele momento.

## Matriz de testes essenciais

| ID | Cenário | Resultado esperado | Fase |
|---|---|---|---|
| T01 | Importar mesmo SQLite/JSON duas vezes | Sem duplicar dados, eventos ou alertas; manifesto reaproveitado | P1 |
| T02 | Importação interrompida e retomada | Transação consistente e retomada idempotente; origem intacta | P1 |
| T03 | Registro legado `auto_sugerida` | Procedência antiga preservada e revisão pendente; não vira enviada comprovada | P1 |
| T04 | Registro aplicado sem origem | Revisão de procedência; data original preservada | P1 |
| T05 | Executar dois boletins/duas datas | Sugestões continuam pendentes até ação real | P1/P5 |
| T06 | Mesmo título/cidade, IDs externos diferentes | Dois anúncios preservados; relação opcional de possível duplicata | P2 |
| T07 | Mesmo ID externo com título novo | Mesma identidade, nova versão e evento de mudança | P2 |
| T08 | Descrição mudou após já estar preenchida | Nova versão, reanálise elegível e artefato anterior preservado | P2 |
| T09 | Retorno sem descrição depois de retorno completo | Não apagar descrição boa; registrar qualidade da observação | P2 |
| T10 | HTTP 200 com login/desafio/layout inesperado | Erro de formato/bloqueio, sem fechar vagas | P2 |
| T11 | Página 1 OK e página 2 falha | Lote parcial; nenhuma ausência/encerramento inferido | P2 |
| T12 | Lista completa válida com zero vagas | Estado vazio real, com política de confirmação antes de fechar | P2 |
| T13 | Fonte falhou por dias | Histórico continua; `last_seen` velho sozinho não encerra | P2 |
| T14 | Fonte secundária sumiu, oficial ativa | Vaga continua ativa; saúde da secundária fica separada | P2 |
| T15 | Política/filtro mudou desde última coleta | Não comparar ausência entre escopos incompatíveis | P2 |
| T16 | Fonte incremental só últimos 3 dias | Coleta completa desse escopo não fecha vagas mais antigas | P2 |
| T17 | Baseline importado ou empresa recém-adicionada | Não chamar todo estoque histórico de lançamento novo | P1/P2 |
| T18 | Datas ISO, dia sem hora, ~data, N/A e texto relativo | Precisão/origem preservadas; sem horário/publicação inventados | P1/P2 |
| T19 | Execução perto de meia-noite UTC | Dia da interface e do digest segue Brasília | P2/P5 |
| T20 | Vaga sem descrição suficiente | Análise parcial, nota nula/limitada e cobertura explícita | P4 |
| T21 | Vaga exige Mecânica e perfil registra Civil | Requisito não marcado automaticamente como atendido | P4 |
| T22 | Texto diz certificado desejável ou não obrigatório | Sem bloqueio automático por palavra-chave | P4 |
| T23 | Certificado obrigatório atual com reciclagem pendente | Lacuna/pendência honesta; não declarar validade | P4 |
| T24 | Perfil atualizado com evidência nova | Nova análise por versão; anterior preservada | P4 |
| T25 | Novo perfil inválido | Última versão válida permanece ativa e falha é visível | P4 |
| T26 | Score histórico no perfil | Não reutilizar como avaliação atual da vaga | P4 |
| T27 | Modelo responde JSON inválido/claim sem referência | Validação falha, resultado não promovido a final | P4/P6 |
| T28 | Número existente em outro contexto | Não validar uma métrica atribuída à experiência errada | P6 |
| T29 | P6/SQL/projeto pessoal descrito como expertise corporativa | Claim bloqueado ou reescrito com qualificador correto | P6 |
| T30 | Repetir coleta sem mudanças | Nenhuma vaga/versão/alerta duplicado | P2/P5 |
| T31 | Dry run de pipeline completo | Hash/contagens do DB real e outbox real inalterados; sem transporte externo | P1/P5 |
| T32 | Flag CLI inexistente | Erro explícito; não executa modo normal por engano | P1 |
| T33 | SMTP erro transitório | Outbox persiste com retry; coleta e painel continuam | P5 |
| T34 | SMTP aceita e conexão fica ambígua | Estado não é “entregue”; retry não duplica cegamente | P5 |
| T35 | SMTP sem credencial e só coleta solicitada | Coleta conclui; e-mail aparece desativado/não configurado | P5 |
| T36 | Processo cai após criar item na outbox | Item recuperável e sem desaparecimento silencioso | P5 |
| T37 | Scheduler/API/CLI disparam juntos | Um ciclo ativo; outros registrados como pulados | P3/P5 |
| T38 | Pasta com espaços e diretório corrente diferente | Scripts e subprocessos usam arquivos corretos | P1/P5 |
| T39 | Exportador e-mail falha, coletor funciona | Dados bons disponíveis imediatamente no painel | P3/P5 |
| T40 | Acessar /_system/config/profile/master.json ou path codificado | 404/403; nenhuma exposição do arquivo | P3 |
| T41 | Mutação de origem externa ou Host inválido | Requisição rejeitada sem enfileirar trabalho | P3 |
| T42 | Texto do anúncio contém HTML/script/instrução ao agente | Exibido de forma segura e tratado como dado | P2/P3/P4 |
| T43 | API de artefato recebe traversal/caminho absoluto arbitrário | Sem leitura fora do diretório autorizado | P3/P6 |
| T44 | Recarregar painel após edição | Estado confirmado persiste e coincide com CLI | P3 |
| T45 | Marcação antiga via export de localStorage | Origem manual preservada; não recebe prova fictícia | P3 |
| T46 | PDF criado com fontes não carregadas/página cortada | Falha de QA; não aparece pronto para envio | P6 |
| T47 | Nova versão de perfil após PDF enviado | Arquivo enviado e associação histórica não mudam | P6 |
| T48 | ATS faz timeout após possível envio | `submission_unknown`; não reaplicar automaticamente | P7 |
| T49 | Exportação parcial para WP | Não emite completude geral nem encerra ausentes | P8 |
| T50 | Backup/restore em cópia com WAL ativo | Snapshot íntegro, artefatos referenciados disponíveis e sem efeitos externos | P1/P9 |

Não é necessário criar 50 funções de teste separadas. Agrupar casos relacionados em testes parametrizados e integração com fixtures. Priorizar os casos da fase atual e os caminhos alterados. Não atribuir resultado aprovado a teste que ainda não foi executado.

## Smoke tests de fontes

Testar uma amostra por plataforma disponível, com limites baixos de requisição e sem candidato logado. Registrar URL, adapter/versão, HTTP/status do contrato, completude, contagem e horário.

Para fonte sem suporte ou bloqueada, um resultado honesto `blocked`/`unconfigured` é preferível a array vazio com sucesso. O painel precisa listar todas as empresas cadastradas, inclusive essas.

A coleta de uma query com janela de 72 horas não prova ausência de vaga antiga. A política de encerramento precisa saber `coverage_kind`, `scope_id` e se o lote autoriza inferência por ausência.

## Critérios de pronto por marco

### M1: histórico confiável

Importação real preservada; relatório de reconciliação; banco original intocado; revisão de 13/15 registros conforme contagens reais; nenhuma candidatura criada por sugestão; datas diferenciadas e backup restaurável.

### M2: busca diária útil

Uma rotina completa de coleta; dados e erros por empresa; mudanças relevantes detectadas; falhas não apagam vagas; painel controla a mesma base; desconhecidos visíveis e nenhum requisito crítico inventado.

### M3: operação autônoma local

Scheduler aponta ao ambiente correto, possui quatro horários pretendidos e não duplica tarefas; execução via scheduler testada sem envio; outbox/preview funcionam; logs contêm run_id e código final. Se e-mail estiver habilitado posteriormente, teste de envio real requer evidência de aceitação e confirmação do usuário sobre recebimento, sem confundir as duas.

### M4: documentos por vaga

Contrato real do Builder testado; claims rastreáveis; JSON válido; PDF com layout e texto verificados; pacote versionado; arquivo associado à candidatura é imutável.

### M5: assistência de candidatura

Formulário local preenchido corretamente; perguntas desconhecidas ficam pendentes; nenhum envio real em teste; estado incerto tratado; não há promessa de um bot universal para Gupy/Workday/etc.

## Evidência que deve ficar em docs/PROGRESS.md

Para cada verificação: comando exato ou teste, ambiente, instante, saída resumida/artefato, resultado, limitação e mudança coberta. “Compilei mentalmente”, arquivo existente, log sem leitura ou README antigo não contam como verificação.

## Revisão de UI

Verificar desktop e largura mobile útil. Avaliar legibilidade, rótulos de estado, conteúdo longo, ausência de fontes/CDN, loading, erro, vazio, paginação, confirmação manual e links. Só marcar UI testada quando a execução real tiver sido inspecionada. Screenshots internos podem apoiar QA; não incluir dados pessoais em relatórios públicos.

## O que não é critério de sucesso

- Número de arquivos criados ou linhas de código.
- Estrelas de repositório externo.
- Quantidade de candidaturas por hora.
- Porcentagem de chance de contratação sem calibração.
- “Tudo atualizado” quando houve fonte indisponível.
- Uma tarefa registrada, mas nunca executada na conta e ambiente corretos.
