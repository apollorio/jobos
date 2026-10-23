# Conflitos encontrados e resolução provisória

| Campo/regra | Fonte A | Fonte B | Resolução operacional provisória | O que falta |
|---|---|---|---|---|
| Local aceito | `rio.ts`: só Grande Rio; bloqueia Macaé, Vitória, Santos, Rio das Ostras, Angra | `profile.yml`: aceita Macaé, Campos, Angra, Vitória, Vila Velha, Serra, ES | `preferences.yaml`: Grande Rio = preferido; Vitória/ES = base secundária aceita; Macaé, Campos e demais RJ = revisar; outros estados = fora da preferência. Nada é escondido: a vaga aparece com motivo | Confirmação do Rafael sobre Macaé/embarque |
| Local vazio | `triage.py`: recusa | `score.py`: aprova | Local desconhecido = "revisar", nunca recusa | |
| Frescor | `triage.py`: recusa acima de 15 dias | sem regra no portal | Idade só entra na prioridade, quando a data é conhecida; data estimada não envelhece vaga | |
| Setor | `triage.py`: exige termos marítimos, exceto empresas-alvo (inclui recrutadoras e Capco) | portal: núcleo por regex | Setor não é filtro; vira informação de prioridade | |
| Exclusão de empregador | `score.py`/`profile.yml`: dragagem (Van Oord, Boskalis...) | `triage.py`: sem exclusão | Exclusão mantida como preferência explícita do usuário (24/08/2026), visível no painel | |
| Candidatura aplicada | `consolidar_pendentes` (13) e marcação manual (15) | sem prova de plataforma | `legacy_needs_review`, fora do total comprovado | Confirmação do usuário por registro |
| Gap profissional | `score.py`: fator 0,75 com `gap_months: 21` fixo | perfil: `career_reentry` | Nenhuma penalidade | |
| Probabilidade de entrevista | `interview_prob` em 1.979 linhas | blueprint proíbe | Preservado só no payload legado; nunca exibido | |
| Corte de descrição | `compat.py` 2.500; `triage.py` 1.500; legado web 6.000; store 20.000 | blueprint: texto completo | Texto completo guardado; truncamento só com registro de tamanho original | |
| Certificados | `profile.yml`: `held: false`, hard gate | `master.json`: "realizado; reciclagem pendente" | Obrigatório atual = pendência (`partial`) com explicação; desejável = sem bloqueio | Documento de renovação |
| Perfil digital | `profile.yml` lista Python/SQL como skills | `master.json`: Python/TS projeto pessoal, SQL/P6 em desenvolvimento | Grafo prevalece; nunca "atendido" profissional | Evidência nova |
| Gestão | textos antigos "5+ anos" | `truth_boundaries.management_tenure`: 3 anos e 5 meses | Requisito de 5+ anos de gestão = lacuna | |
| Capco | YAML: quadro global (1.306 linhas no banco) | TS: só escritório 114971 (Rio) | Escopo filtrado por escritório; linhas globais importadas ficam "não verificadas" | |
| Yinson | YAML tem "Yinson" (J2W) e "Yinson Production" (unknown) | | Uma empresa, um source | |
| Estágio seletivo | SQLite local | WordPress editável | Local é autoridade; integração WP desligada | Contrato por campo (P8) |
| Marcações do portal | `localStorage` (`jobos-saved`, `jobos-muted`) | SQLite | Importação só por exportação do navegador, com origem `browser_export`; Python não lê o navegador | Exportação manual pelo usuário |
| Porta do painel | blueprint: 8765 | 8765 ocupada por outro projeto | 8766 em `config/app.yaml` | |
| Tarefas legadas | `jobos-vagas - ciclo 12h/18h` | caminho inexistente | Exportar XML e desativar (não apagar) ao instalar a tarefa nova | |
