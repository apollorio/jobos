# Auditoria dos anexos e decisões de reaproveitamento

Inspeção estática feita em 22/10/2026. Bancos foram abertos em modo somente leitura. Não executei o motor legado, não testei todos os ATS ao vivo, não enviei e-mail e não acessei o disco D: do Rafael. Afirmações de funcionamento em READMEs antigos precisam de nova evidência no ambiente real.

## 1. O que veio nos anexos

| Arquivo | Conteúdo observado | Decisão |
|---|---|---|
| `Artifact.zip` | Projeto Python `jobos/`, SQLite, testes, scripts Windows, configuração e exportadores | Base preferencial do engine Python, com correções antes de rodar |
| `web-vagas(1).zip` | Portal JOBOS, 28 empresas, leitores TS, confirmação de página e service worker | Base preferencial de interface e fonte complementar de leitores |
| `apollo-vagas_1.zip` | Plugin WordPress com CPT, REST, Kanban e importação por arquivo | Preservar; integrar depois do núcleo local |
| `manifest(1).zip` | Outro pacote do portal com sobreposição de arquivos | Comparar por arquivo; não extrair por cima de versões divergentes |
| `index(6).html` | Entrada HTML que depende de assets JS/CSS | Reaproveitar interface, não tratar como aplicação autossuficiente |
| `jobs(1).json` | 28 empresas e 252 ofertas no snapshot | Importar como histórico de descoberta |
| `rvalle.com.br-rafael(1).json` | Grafo completo da carreira com 32 módulos de topo | Fonte local de fatos pessoais |
| `manifest.webmanifest` / `sw.js` | Manifesto e cache do portal | Ajustar escopo de cache e caminhos após API local |

Os arquivos antigos `web-vagas.zip`, `manifest.zip`, `jobs.json` e `rvalle.com.br-rafael.json` disponíveis nesta conversa foram comparados com seus correspondentes `(1)`: cada par era binariamente idêntico. Isso não demonstra que os arquivos extraídos no PC continuam iguais.

## 2. Banco legado: resultado observado

Arquivo: `Artifact.zip → jobos/jobs.db`.

| Métrica | Resultado |
|---|---:|
| Linhas em `jobs` | 1.118 |
| Eventos em `events` | 2.295 |
| Linhas em `runs` | 251 |
| `application_status='applied'` e origem `auto_sugerida` | 13 |
| `application_status='applied'` e origem nula | 15 |
| `application_status='new'` | 1.090 |
| `PRAGMA integrity_check` | ok |

Esses números são do anexo. Não significam 1.118 vagas atualmente abertas nem 28 candidaturas comprovadas. A revisão de procedência é necessária. `out/dry.db` é outro banco com cinco vagas de teste; não deve virar banco de produção por engano.

## 3. Python já existente

| Arquivo | Responsabilidade existente | Reaproveitamento |
|---|---|---|
| `run.py` | Comandos discover, score, digest, boletim, sync e ciclo | Converter em CLI estrita e serviços sem efeitos implícitos |
| `jobos/store.py` | Esquema SQLite, upsert, identidade e fechamento | Migrar dados; corrigir identidade, atualização e encerramento |
| `jobos/fontes.py` | Seleção de leitores, mapeamento e enriquecimento | Reaproveitar interfaces e fallback, registrando completude |
| `jobos/sources/gupy.py` | Tenant Gupy e portal de vagas | Testar e aproveitar se contrato atual funcionar |
| `jobos/sources/ats.py` | Adaptadores de ATS | Aproveitar por plataforma após smoke test |
| `jobos/sources/web.py` | Leitores web por empresa/plataforma | Mapear cobertura e corrigir fragilidades concretas |
| `jobos/sources/totvs.py` | Coleta TOTVS | Testar paginação e origem de datas |
| `jobos/sources/adzuna.py` | Fonte opcional com credenciais próprias | Não tornar obrigatória para primeira entrega |
| `jobos/resilience.py` | Tentativas e memória de estratégias | Reaproveitar com limites e proveniência |
| `jobos/preflight.py` | Saúde e volume das fontes | Incorporar ao resultado de cada run |
| `jobos/score.py` | Gates e score por componentes | Extrair partes úteis; remover probabilidade não calibrada |
| `jobos/triage.py` | Portões de local, setor, função, senioridade e frescor | Converter políticas em configuração única |
| `jobos/compat.py` | Outro cálculo de compatibilidade | Consolidar, evitando duas notas conflitantes |
| `jobos/autoapply.py` | Sugestão e consolidação presumida de candidatura | Remover presunção; reaproveitar eventos manuais úteis |
| `jobos/bulletin.py` / `digest.py` | Boletim e SMTP | Separar renderização, outbox e transporte |
| `jobos/diff.py` | Comparação entre resultados | Usar após corrigir identidade e estados |
| `jobos/sync.py` | Exportação para arquivo do plugin | Manter como integração opcional e contratada |
| `jobos/wordpress.py` | Payload/envio para WP com filtros próprios | Desativado inicialmente; unificar políticas antes de reusar |
| `tools/truth_lint.py` | Verificações textuais de alegações | Heurística auxiliar, insuficiente como validador semântico |
| `tests/` | Testes de score, triagem e dry run | Classificar por comportamento válido; ajustar testes que cristalizam erro |
| `windows/*.ps1` | Scripts de execução e horários antigos | Substituir caminhos e fluxo; preservar backups |

Dependências declaradas: `requests>=2.32`, `PyYAML>=6.0`, `python-dateutil>=2.9` e `rapidfuzz>=3.9`. São limites inferiores, não um lock reproduzível.

## 4. Correções prioritárias verificadas no código

| ID | Evidência | Consequência | Ação exigida |
|---|---|---|---|
| A01 | `autoapply.consolidar_pendentes()` muda sugestões antigas para `applied`; `run.boletim()` a chama antes de renderizar | Histórico confunde sugestão com candidatura | Desativar fluxo; migrar registros como revisão de procedência |
| A02 | `store.job_id()` usa empresa + título + localização truncada para gerar hash curto | Pode fundir vagas distintas e separar a mesma vaga quando título muda | Identidade por fonte/tenant/ID, com UUID canônico e mapa legado |
| A03 | `store.upsert()` preenche descrição só quando antes vazia | Mudanças reais de requisitos ficam invisíveis | Versionar conteúdo e atualizar por qualidade/proveniência |
| A04 | `store.mark_closed()` encerra por `last_seen` antigo | Fonte com erro ou fora da coleta pode fechar vagas indevidamente | Fechamento condicionado a coletas completas e evidência por fonte |
| A05 | `store.upsert()` usa `~YYYY-MM-DD` em `date_posted` quando a publicação falta | Data detectada divide campo com publicação | Separar data/origem/precisão sem perder texto original |
| A06 | `score.py`, `triage.py` e `compat.py` aplicam políticas e notas diferentes | E-mail, exportação e painel podem discordar | Um serviço de análise e preferências, contratos únicos |
| A07 | `score.interview_probability()` usa fórmula heurística e penalidade por gap | Porcentagem sem base de calibração aparece como chance de entrevista | Descontinuar apresentação e uso como probabilidade |
| A08 | `compat.calcular()` considera só os primeiros 2.500 caracteres de descrição | Requisitos posteriores podem desaparecer | Extrair seções completas e explicitar truncamento quando inevitável |
| A09 | Linter verifica corpus textual, tokens, números e padrões | Número ou ferramenta em outro contexto pode passar sem sustentar claim | Validar relação claim-evidência e qualificadores |
| A10 | Script Windows aponta para `D:\dev\jobos` e pasta antiga de plugin | Não corresponde à raiz atual solicitada | Resolver caminhos pela raiz nova, com override configurável |
| A11 | Scripts antigos propõem horários diferentes: 12h/18h e 13h | Duplicidade ou execução fora da intenção atual | Um agendamento canônico de 08h/12h/14h/18h |
| A12 | Ciclo captura exceções de etapas e imprime falhas sem estruturar retorno final confiável | Scheduler pode interpretar ciclo parcial como sucesso | Retornos explícitos e código de saída coerente em todas as camadas |
| A13 | PowerShell usa `python` no PATH e um placeholder de senha no script | Ambiente e credenciais dependem da sessão | Python absoluto, ambiente resolvido e segredos fora do código |
| A14 | `merge-jobs.ts` finaliza vaga ausente mesmo quando a listagem não veio vazia | Guard de duas leituras vazias não protege paginação parcial | Centralizar fechamento no engine e manter coleta TS sem mescla |
| A15 | `rio.ts` bloqueia Macaé, Vitória, Santos e outras cidades e exige Grande Rio | Preferências mais amplas não chegam à análise | Importar como política antiga; controles configuráveis sem rejeição oculta |
| A16 | `host.ts` usa `0.0.0.0` por padrão e permite vários tipos de arquivos sob sua raiz | Novo `_system/*.json` poderia ficar acessível se o host antigo servisse a árvore | Loopback e allowlist estática; bloquear árvore privada no servidor/publicação |
| A17 | `jobos.js` persiste marcações no `localStorage` | Python e outro navegador não conhecem o estado real | API SQLite e importação opcional do estado exportado pelo navegador |
| A18 | Python e TS já têm leitores sobrepostos para Gupy/ATS | Dois coletores independentes podem divergir e gravar estados concorrentes | Um principal e fallback explícito por fonte |
| A19 | Exportadores aplicam recortes próprios; WP pode interpretar exportação como completa | Fonte parcial pode virar encerramento no destino | Contrato de completude por empresa e exportações separadas |
| A20 | `sync.py` e comentários do plugin pressupõem RealTimeSync e caminho antigo | Publicação automática pode levar dados privados/obsoletos | Integração desligada até validar destino e allowlist |

## 5. O que não deve ser herdado como verdade atual

O README do Python contém recomendações anteriores por GitHub Actions, cron em hospedagem, limites de certificado e carreira, contagens de testes antigos e exclusões de empregadores. Essas frases não substituem a intenção atual do Rafael nem provam acesso a uma conta ou serviço.

Preferências de emprego são diferentes de fatos profissionais. Extrair os filtros legados e mostrá-los em `docs/CONFLICTS.md`. Se um filtro rigoroso antigo conflitar com o perfil canônico e o pedido atual, mantê-lo como preferência pendente ou filtro visível, sem sumir com vagas silenciosamente.

Certificados historicamente realizados e reciclagem pendente estão no JSON canônico. Não extrapolar prazo de validade de uma norma inteira, não formular aconselhamento jurídico e não declarar que qualquer vaga offshore é automaticamente inviável.

## 6. Empresas do snapshot web

Plataformas observadas no campo `kind`:

| Tipo | Empresas |
|---|---:|
| gupy | 13 |
| sf | 4 |
| workday | 4 |
| smart | 2 |
| inhire | 1 |
| oracle | 1 |
| dof | 1 |
| bram | 1 |
| greenhouse | 1 |

Empresas: PRIO, MODEC, Norsul, Brava Energia, Wilson Sons, Ocyan, Qualidados, Oceânica, Vinci Energies, Nexa Tecnologia, Enauta/tenant legado 3R, Minsait, Vibra, Subsea7, SBM Offshore, Yinson, Halliburton, Transocean, Equinor, Shell, Baker Hughes, Aker Solutions, Airswift, OceanPact, ABS, DOF, Bram Offshore e Capco.

Essas identidades e tenants são registros do snapshot, não prova de marca/tenant atual. Rebrandings e portais migrados precisam de validação por fonte, com alias e histórico em vez de troca cega de domínio.

## 7. Perfil profissional: limites importantes presentes no JSON

- Graduação em Engenharia Civil; técnico em Portos; MBA em Gestão de Projetos e pós-graduações registradas no grafo.
- Van Oord com período formal de 12/07/2021 a 01/11/2024; usar redação canônica segura `3+ anos`, sem inflar para 5+ anos de gerência equivalente.
- Experiência forte em operações marítimas, interface base/embarcação, planejamento, logística, HSEQ e execução de projetos.
- CREA ativo segundo o perfil. Não inferir área de atribuição profissional além do documentado.
- Certificados CBSP/BOSIET/HUET/T-HUET históricos, com reciclagem pendente; não alegar validade atual.
- Python/TypeScript em projetos pessoais/desenvolvimento e SQL em desenvolvimento. Power BI tem registro de uso comprovado.
- Não alegar Master Mariner, Ciências Náuticas, operação de produção de FPSO, ownership de PMS/CMMS, auditor líder ou experiência corporativa em Primavera P6 sem evidência nova.
- Pretensão salarial e regime CLT/PJ aparecem como desconhecidos. Não inventar salário mínimo nem resposta de formulário.
- Mobilidade tem base principal RJ e secundária Vitória; priorização atual shore-based/onshore, com detalhes de embarque e mudança a esclarecer conforme vaga.

Este documento não é um novo currículo. Claude deve consultar os caminhos de dados reais ao gerar qualquer afirmação final.
