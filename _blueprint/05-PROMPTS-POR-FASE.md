# Prompts de execução e retomada

Os prompts abaixo pressupõem que o mestre já foi lido e o blueprint está em `_system/_blueprint`. Não são dependências adicionais nem pedidos de replanejamento.

## A. Retomada sem perder contexto

```text
Retome o JOBOS em D:\dev\_dev web\_rvalle-site\__VAGAS\_system.
Leia instruções locais aplicáveis, CLAUDE.md, docs/PROGRESS.md, docs/DECISIONS.md e o diff atual. Consulte só os trechos do blueprint relevantes à próxima fase.
Não reinicie o projeto nem repita auditorias já concluídas sem sinal de mudança. Confirme o último resultado verificado, identifique o próximo item aberto e implemente-o agora. Preserve minhas alterações.
Se falta credencial ou integração externa, registre bloqueio específico e prossiga em trabalho independente. Atualize checkpoint com os comandos reais, resultados e próxima ação exata antes de encerrar.
```

## B. P0: auditoria e consolidação

```text
Execute P0 do blueprint e continue diretamente ao início de P1. Leia arquivos reais e compare ZIPs/pastas sem sobrescrever divergências. Inspecione os bancos em modo somente leitura e faça backup consistente. Não execute o ciclo legado: há SMTP, sync e consolidação de sugestões em candidaturas.
Entregue AUDIT.md, REUSE-MAP.md, SOURCE-COVERAGE.md e CONFLICTS.md com evidência por arquivo/função. Capture contagens antes de migrar. Verifique se _system seria publicado por host.ts, servidor local ou RealTimeSync e prepare isolamento.
Escolha o caminho de menor mudança que preserve dados e elimine autoridade duplicada. Em seguida implemente pacote, settings e doctor. Não finalize só com uma proposta.
```

## C. P1: importação correta

```text
Implemente P1 usando o banco legado como origem imutável e data/jobos.sqlite3 como base canônica. Migrações versionadas, import manifests, legacy_id_map e hashes. Importe SQLite e jobs.json sem alertar histórico como lançamento atual.
Remova todos os caminhos sugestão -> candidatura. Os registros auto_sugerida e applied sem origem precisam de revisão, preservando valores originais. Separe anúncio, preparação/envio e processo seletivo.
Implemente import-legacy em modo relatório e modo apply, status e backup. Verifique importar duas vezes, interromper/repetir importação e contagens antes/depois. Nenhuma mensagem externa. Atualize checkpoint e prossiga para coleta.
```

## D. P2: fontes sem fechamentos falsos

```text
Implemente SourceBatch e selecione um leitor principal por fonte na matriz. Reaproveite Python existente; use bridge TS somente onde trouxer cobertura melhor. Coletores não gravam estado nem enviam alertas.
Valide formato, paginação, limites, timeout, Retry-After, erros e completude. Atualize descrições/versione mudanças. IDs externos distintos não podem colapsar por título igual.
Uma fonte parcial ou com erro não pode incrementar ausência nem encerrar vaga. Ausência de uma fonte secundária não fecha anúncio canônico ativo. Crie fixtures dos formatos reais, testes de falha e um smoke test de leitura limitado, registrando resultado atual sem prometer todas as plataformas.
Conecte CLI e pipeline à persistência e ao relatório de saúde. Prossiga ao painel.
```

## E. P3: painel que controla a base real

```text
Reaproveite o portal JOBOS e crie API local para a mesma base da CLI. Não redesenhe tudo. Use somente assets permitidos, bind 127.0.0.1, proteção de mutações e downloads por ID autorizado; não sirva _system nem __VAGAS inteiro.
Implemente overview, fontes, vagas, candidaturas, arquivos e diagnóstico. Ações longas usam fila persistente. Um GET não inicia coleta. Mostre estados vazios, pendentes, parciais e erros sem dados fictícios de produção.
Marcação manual de candidatura registra user_asserted; prova automática usa procedência separada. Carregue a página de novo e confirme persistência. Alerte dependência de CDN ou asset ausente com fallback legível. Faça verificação visual real do painel e atualize documentação de inicialização.
```

## F. P4: compatibilidade com evidência

```text
Implemente o contrato de análise do blueprint. Perfil canônico completo, requisitos extraídos da descrição completa e quatro estados: atendido, parcial, lacuna comprovada, desconhecido. Todo vínculo de evidência precisa resolver no JSON e sustentar o contexto.
Unifique as decisões hoje distribuídas em score.py, triage.py e compat.py. Remova interview_prob da experiência do usuário e da priorização. Mostre cobertura e método; baixa informação não recebe falsa precisão. Preferências de empresa/local são separadas de capacidade técnica.
Não invente formação, salário, validade de curso, meses de experiência ou expertise. Leia negação e obrigatoriedade do texto. Funcione sem IA, com provider opcional sem segredos obrigatórios e cache por todas as versões relevantes.
Valide casos de Engenharia Civil versus Mecânica, P6 em desenvolvimento, certificado com reciclagem pendente, desconhecido e experiência transferível. Não elimine vaga só por aparecer offshore.
```

## G. P5: operação sem silêncio enganoso

```text
Implemente outbox persistente e preview texto/HTML/.eml. Teste transporte falso com sucesso, erro transitório, autenticação inválida e resultado incerto. Coleta e painel continuam mesmo quando notificação falha. Não chame aceitação SMTP de entrega confirmada. Não envie e-mail real nesta fase sem configuração e instrução de ativação.
Implemente scripts Windows de bootstrap, execução, dashboard, agendamento, status e remoção de tarefas próprias. Uma tarefa ou configuração idempotente deve cobrir 08h/12h/14h/18h de Brasília. Use Python absoluto e working directory. Trava entre CLI/API/scheduler, códigos de saída e logs corretos. Liste tarefas antigas para evitar duplicidade, preserve XML e não mexa em tarefas alheias.
Faça execução manual, preview e teste do scheduler em modo sem envio. Documente limitações de timezone, energia, login e rede com o que foi observado neste PC.
```

## H. P6: currículo fiel e exportável

```text
Localize o código local do CV Builder relacionado a cv.rvalle.com.br/v2. Não suponha que os anexos já o contêm e não invente seu schema. Inspecione importação, exemplo real de JSON e CSS de impressão; extraia um contrato validado e um teste de roundtrip.
Gere claims estruturados a partir do perfil e da vaga. Valide referências, status de competência, qualificadores, datas, sujeito, contexto e número/unidade. O linter antigo é só uma checagem adicional.
Converta para o JSON real do Builder, renderize localmente com fontes prontas e gere PDF com texto selecionável. Inspecione páginas/cortes e extraia texto para verificar identidade, cargo e conteúdo. Guarde pacote versionado com hashes. Não sobrescreva arquivos já associados a candidatura enviada.
Se o Builder não estiver no disco e não for possível obter seu contrato, registre exatamente o que falta e continue outras tarefas; não declare compatibilidade fictícia.
```

## I. P7: preencher sem inventar envio

```text
Implemente o fluxo assistido primeiro em formulário local de teste. Browser state em diretório privado dedicado, nunca no navegador pessoal. Preencha campos conhecidos e anexe o PDF correspondente à vaga; resposta desconhecida vira pendência.
Para Gupy/ATS real, diferencie coletar vagas, preencher formulário e enviar candidatura. Leia os requisitos do fluxo realmente acessível; não presuma que uma API pública de listagem permite POST de candidatura. Não altere meu currículo global da Gupy para cada vaga automaticamente.
Pare em awaiting_review e não clique envio final real nesta fase. MFA, CAPTCHA, teste e consentimentos precisam de usuário. Se um envio futuro ficar incerto, registre submission_unknown e reconcilie antes de repetir.
```

## J. P8 e P9: integrar e observar

```text
Crie exportadores separados para o portal antigo e o plugin WordPress. Local é a autoridade inicial. Dados públicos usam allowlist; currículo, notas, score pessoal e estado de candidatura permanecem privados. Fonte parcial nunca gera completo=true nem fechamento no destino.
Não ative push, deploy ou RealTimeSync. Produza somente preview/fixture de payload e documentação de contrato. Se houver edição em WordPress no futuro, defina ownership por campo e conflito, sem sincronização bidirecional improvisada.
Monte relatório de operação por fonte, execuções atrasadas e divergências. Registre falhas reais e calibração humana. Teste restauração de backup em cópia, não sobre o banco ativo.
```

## K. Revisão de entrega

```text
Revise a implementação JOBOS contra 07-VALIDACAO-ACEITE.md. Foque bugs que poderiam perder histórico, inventar candidatura, fechar vaga em falha, inflar currículo, servir arquivo privado ou declarar e-mail enviado sem evidência.
Execute verificações adequadas nas partes alteradas, corrija os problemas e registre limitações. Não amplie escopo por estilo nem repita testes já aprovados sem mudança relevante. Atualize README, comandos realmente existentes, PROGRESS e testes com seus resultados reais. Informe como eu inicio e uso o que está pronto.
```
