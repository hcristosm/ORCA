# ORCA

Dashboard estático que cruza setorização de risco geológico (CPRM/SGB) com chuva
recente (INMET/ANA/Open-Meteo), para as 27 UFs. Sem backend: o pipeline Python
gera JSON/GeoJSON e o front-end estático em `docs/dashboard/` os consome.

## A prioridade é confiabilidade, não recursos novos

O pipeline depende de fontes `.gov.br` que caem, mudam schema e devolvem resposta
vazia com HTTP 200. **Funcionar sem paus vale mais que qualquer funcionalidade
nova.** Ao mexer em ingestão, assuma que a fonte vai falhar e trate o caso.

## Fluxo de dados

```
ingest/ ──→ data/*.gpkg, *.csv ──→ processing/ ──→ export/ ──→ docs/dashboard/data/
(CPRM, INMET,     (local, fora     (cruzamento     (GeoJSON +      (publicado em
 ANA, Open-Meteo)  do git)          espacial)       JSON)           gh-pages)
```

- `src/ingest/` — um módulo por fonte: `cprm.py` (setores de risco, mensal),
  `inmet.py` (chuva horária histórica), `ana.py` (estações telemétricas),
  `openmeteo.py` (chuva por ponto, fonte padrão). `rate_limiter.py` é
  compartilhado.
- `src/processing/` — `cruzamento.py` liga setor↔chuva (centroides, estação mais
  próxima), `grade_espacial.py` monta a grade adaptativa nacional,
  `previsao.py` calcula a trajetória de 72h.
- `src/export/` — `dashboard_data.py` exporta uma UF, `nacional.py` orquestra as 27
  com uma grade compartilhada.
- `src/storage_cache_openmeteo.py` — cache SQLite incremental, sincronizado entre
  runs de CI via `gh-pages`. É o que evita reconsultar a Open-Meteo inteira todo dia.
- `src/config.py` — **toda convenção de caminho mora aqui.** Nunca monte um caminho
  de `data/` à mão; use `caminho_setores()`, `caminho_chuva()`, etc.

## Comandos

```bash
# Testes e gates (o CI roda os quatro; rode antes de commitar)
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
.venv/bin/python -m bandit -q -c pyproject.toml -r src

# Se o .venv estiver incompleto (já aconteceu):
.venv/bin/pip install -e ".[dev]"

# Dashboard local em http://localhost:8000/dashboard/
scripts/rodar_dashboard.sh

# Pipeline (os dois comandos que os workflows chamam)
python -m src.cli ingerir-setores --diretorio data      # mensal, CPRM/SGB
python -m src.cli atualizar-nacional --ufs SP,RJ        # diário, Open-Meteo

# Por UF, uso manual
python -m src.cli exportar-dashboard --uf SP
python -m src.cli atualizar --uf SP --ano 2026
```

## Saídas e contratos do dashboard

Por UF, em `docs/dashboard/data/` (tudo em minúsculas):
`setores_<uf>.geojson`, `series_<uf>.json`, `previsao_<uf>.json`, `meta_<uf>.json`.

`ufs_disponiveis.json` lista as UFs publicadas e **guia o seletor do front-end** —
é também a métrica da guarda anti-regressão (abaixo). O front-end é JS puro, sem
build: `index.html`, `areas-customizadas.js`, `relatorio.js`.

## Publicação: a regra que não se quebra

O deploy usa `force_orphan`, então **`gh-pages` vira exatamente o conteúdo de
`docs/dashboard/`**. Publicar com `data/` vazio apaga as 27 UFs e o cache junto.

Foi assim que os runs **#23 e #29 destruíram o dashboard — ambos fechando como
`success`**. Daí duas regras permanentes:

1. **Nunca julgue um run pelo status.** Meça o resultado nos logs (contagem de UFs,
   limiares) — `success` não prova que publicou dado bom.
2. **Publicação parcial é aceitável; publicar menos do que já está no ar, não.**
   A guarda "Conferir antes de publicar" em `atualizar-dados.yml` recusa quando
   `atual < publicado`, quando `atual = 0`, ou quando a contagem publicada é
   indisponível. Na dúvida, não publica.

A guarda sempre **grava `publicar=false` no `$GITHUB_OUTPUT` antes de sair com 1** —
nessa ordem. É o output que pula a publicação; o exit 1 existe para a recusa ficar
visível. Uma guarda que recusasse em silêncio num cron diário poderia bloquear a
publicação por semanas sem ninguém notar. Se for mexer nesse passo, preserve as duas
propriedades.

## Branches

- `main` — código.
- `dados-base` — setores da CPRM ingeridos (mensal, isolado do pipeline diário).
- `gh-pages` — dashboard publicado + cache da Open-Meteo.

## Convenções

- Código, commits, docs e mensagens ao usuário **em português**.
- Commits no padrão Conventional Commits; o `CHANGELOG.md` agrupa por
  `FEATURES`/`FIXES`/`REFACTOR`/`CHORE` (entradas até a v1.0.0 usam o formato antigo).
- Release: bump em `pyproject.toml` + entrada no CHANGELOG + tag `vX.Y.Z`. A tag
  dispara `release.yml`; confira que os artefatos existem, não só que o run passou.
- `data/` e `docs/dashboard/data/` são ignorados pelo git — são gerados.
- XML da ANA é parseado com `defusedxml`, nunca com `xml.etree` puro.
