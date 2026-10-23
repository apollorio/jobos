# Memória operacional e decisões

## 1. CLAUDE.md sugerido

Criar ou integrar ao CLAUDE.md existente sem apagar regras válidas. O exemplo abaixo é conteúdo proposto; atualizar comandos quando a implementação realmente existir.

```markdown
# JOBOS local

Engine: esta pasta `_system`. Workspace: `D:\dev\_dev web\_rvalle-site\__VAGAS`.
Leia `docs/PROGRESS.md` para retomar e `docs/DECISIONS.md` antes de mudar arquitetura.

Regras centrais:
- Reaproveite Python/portal existentes; não crie outro motor concorrente.
- SQLite é autoridade do estado; JSONs de portal são exportações.
- `config/profile/master.json` é autoridade de carreira; respeite boundaries e evidências.
- Sugestão, e-mail ou CV gerado nunca significa candidatura enviada.
- Fonte parcial/falha não fecha vaga por ausência.
- Datas de publicação e detecção são distintas; instantes em UTC, interface em Brasília.
- `_system` e dados privados não são diretório estático/publicável.
- Dry run não envia nem altera estado de negócio real.
- Envio externo/publicação desativados no bootstrap inicial.
- Preserve dados/alterações do usuário; migre com backup e relatório.

Detalhes: `_blueprint/02-ARQUITETURA-CONTRATOS.md`.
Critérios: `_blueprint/07-VALIDACAO-ACEITE.md`.
Atualize PROGRESS ao concluir uma unidade verificada e antes de interrupção.

Comandos: preencher abaixo somente depois de implementar e testar.
```

Evitar colar dez documentos inteiros no CLAUDE.md. Regras essenciais cabem em texto curto; detalhes são carregados conforme a etapa. Instruções não substituem validação no código.

## 2. Modelo de docs/PROGRESS.md

```markdown
# Progresso real do JOBOS

Atualizado em: <instante com fuso>
Ambiente: <Windows/WSL; Python; Node se usado>
Raiz confirmada: <caminho real>
Fase atual: <P0...P9>
Última entrega verificável: <resultado concreto>

## Concluído

- [x] <resultado e evidência>
- [ ] <próximo comportamento a implementar>

## Arquivos alterados nesta unidade

<arquivo e finalidade>

## Verificações

| Comando/teste | Resultado real | O que verifica | Limite |
|---|---|---|---|
| <comando> | <pass/fail/blocked> | <comportamento> | <não verificado> |

## Dados

Banco origem/hash: <valor real>
Banco canônico: <caminho>
Importação: <id e contagens antes/depois>
Revisões de procedência: <quantidade real>
Backup/restore: <evidência>

## Bloqueios específicos

<integração; dado ausente; ação independente possível>

## Próxima ação exata

<uma ação executável, arquivo alvo, resultado esperado e teste>

## Comandos para retomar

<comandos realmente disponíveis, sem segredos>
```

## 3. Modelo de decisão

```markdown
## DEC-001: título curto

Estado: proposto | aceito | substituído
Contexto observado: arquivo/função/dado real
Decisão: o que será feito
Motivo: problema concreto resolvido
Alternativas descartadas: somente as que afetam tradeoff real
Consequência: dados, compatibilidade e limites
Validação: como verificar
Reversão: backup/migração/flag aplicável
```

Decisões iniciais a registrar:

1. Python local como coordenador e SQLite como autoridade.
2. Migração preservando original e procedência incerta.
3. Seleção de leitor principal por fonte, com fallback sem gravação autônoma.
4. Perfil canônico versus preferências operacionais.
5. Remoção da candidatura presumida.
6. Separação de publicação/detecção e mudanças.
7. Política de encerramento por escopo completo.
8. Política de score e cobertura, sem probabilidade de contratação.
9. Estratégia de isolamento dos arquivos privados sob árvore de site.
10. Momento e contrato de integração do CV Builder e WordPress.

## 4. Modelo de conflito

| Campo/regra | Fonte A | Fonte B | Resolução operacional provisória | O que falta |
|---|---|---|---|---|
| Local aceito | Grande Rio no TS | YAML com locais adicionais | Filtro visível e configurável; preservar vagas | Preferência atual por regime/local |
| Candidatura aplicada | Flag antiga | Sem prova/origem | Legacy needs review, fora de total comprovado | Confirmação do usuário |
| Perfil digital | Texto legado | Grafo com status por habilidade | Grafo prevalece; qualificador obrigatório | Evidência nova, se houver |
| Certificado | Realizado no passado | Validade não atual | Histórico/reciclagem pendente | Documento de renovação |
| Estágio | SQLite local | WordPress editável | Local é autoridade inicial; não ativar bidirecional | Contrato por campo |

Nem todo conflito exige parar e perguntar. Aplicar default conservador que preserve informação e permita continuidade. Quando a escolha altera uma resposta factual da candidatura, deixar pendência específica.

## 5. Relatório ao Rafael

Ao concluir uma sessão, informar em linguagem direta:

1. O que já funciona e como abrir.
2. Quais dados foram preservados e o que precisa de revisão.
3. O que foi testado no PC de verdade.
4. O que depende de credencial, conta ou arquivo ausente.
5. Próximo resultado concreto, sem prometer cron, e-mail ou submissão ainda não verificados.

Não apresentar uma extensa cronologia de comandos como substituto do resultado. Não declarar “100% funcionando” por testes offline de poucas fontes.
