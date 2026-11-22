# Rafael Perini Valle — Bible Database

Fonte única de verdade (121 partes JSON pequenas) + verificador de compatibilidade de vagas.

## Verificar uma vaga
```powershell
node tools/match.mjs --file vaga.txt --format text      # exit 0 = compatible, 1 = not compatible
node tools/match.mjs --json vaga.json                   # saída JSON: "compatible": true|false
node tools/match.mjs --batch-db                         # reavalia as 65 vagas do jobOS
```
Entrada JSON aceita: title/titulo, company/empresa, location/local, description/descricao, date_posted.

## Reconstruir índice e bundle
```powershell
node tools/build.mjs     # valida referências, gera index.json e _bundle/rafael-bible.full.json
```

## Estrutura
`00_meta` fontes/schema/pendências · `01_identity` · `02_profile` · `03_education` · `04_experience` · `05_projects` · `06_skills` · `07_ai` · `08_dev_environment` · `09_domains` · `10_career_strategy` (preferências, tiers) · `11_truth` (limites, lacunas) · `12_cv_variants` (18 CVs) · `13_applications` (65 vagas) · `14_matching` (motor).

## Regras
- Cada parte: `{ "_part": {...}, "data": ... }`. Edite partes, nunca `_bundle/`.
- Nada é inventado: `proven/used` entram em CV sem qualificador; `developing`, `personal-project`, `adjacent` exigem ressalva; `do-not-claim` nunca. Veja `11_truth/`.
- Ajuste de pesos/limiares: `14_matching/engine_config.json`; léxico de requisitos: `14_matching/concepts.json`.
- Originais em `____json/` permanecem intactos (3 duplicatas exatas: master/rvalle.com.br-rafael/MASTER_DATABASE; PROFILE_OFFSHORE e `(1)`).
