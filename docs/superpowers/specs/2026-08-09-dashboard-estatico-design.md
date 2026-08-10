# Dashboard estático (substitui o Streamlit)

Data: 2026-08-09

## Contexto

O dashboard atual (`src/dashboard/app.py`, Streamlit) tem estética genérica
(chrome padrão do Streamlit), limitações de layout (grid fixo de colunas,
sidebar cinza padrão) e não é distribuível como site estático — precisa de
um processo Python rodando. O projeto já tem uma landing page estática em
`docs/index.html` (GitHub Pages) com um sistema de design próprio derivado
das cores/tipografia/espaçamento do Streamlit atual
(`docs/_ds/.../tokens/*.css`), mas com dados fake — não é o dashboard real.

Decisão: substituir o dashboard Streamlit por um site estático em
`docs/dashboard/`, publicado no mesmo GitHub Pages, consumindo dados
pré-computados por um passo novo na pipeline de ingestão/cruzamento
existente.

## Decisões confirmadas com o usuário

1. Site estático com dados pré-computados pelo cron diário (não backend ao
   vivo) — resolve a queixa de distribuição.
2. Layout com filtros numa barra superior fina e o mapa em destaque
   (mais espaço horizontal pro elemento mais denso de informação).
3. Remove os seletores de UF e Ano (só SP tem dados hoje; a ingestão
   incremental do INMET já acumula continuamente) — mostra sempre os dados
   mais recentes de SP. Volta como seletor quando houver mais UFs.
4. Troca o botão "Baixar/atualizar dados agora" por um selo de última
   atualização (sem backend, não há o que baixar sob demanda).
5. Remove o checkbox de auto-refresh (sem processo rodando em segundo
   plano, não há "novo dado chegando" pra verificar).
6. Mantém o indicador de fonte da estação (INMET/ANA) no tooltip do mapa e
   na tabela de setores em atenção.
7. Remove o dashboard Streamlit por completo (não mantém como alternativa
   local) — um único caminho de UI.
8. Publicação: o cron diário gera os arquivos de dados e os comita de
   volta no repositório (bot commit); GitHub Pages publica automaticamente
   por já servir `/docs`. (Alternativa mais "correta" — deploy via
   artefato do GitHub Actions, sem poluir o histórico — exigiria mudar a
   configuração de Pages do repositório manualmente nas configurações do
   GitHub, fora do que dá pra fazer só com git; descartada por ora.)

## Exportação de dados (`src/export/dashboard_data.py`, novo)

Uma função `exportar_dashboard(uf, diretorio_dados, saida_dir) -> dict`
que:

1. Lê os setores (`ler_setores`), a chuva do INMET (`ler_chuva`) e, se
   existir localmente, a chuva da ANA — mesmo padrão de carregamento hoje
   usado pelo dashboard Streamlit.
2. Roda `calcular_cruzamento(setores, chuva_inmet, chuva_ana=chuva_ana,
   janelas=(24, 72))` (já combina INMET+ANA e produz `fonte_estacao`).
3. Grava três arquivos em `saida_dir` (`docs/dashboard/data/`):
   - **`setores_<uf>.geojson`**: um `Feature` por setor com as
     propriedades `num_setor, munic, grau_risco, distancia_km, chuva_24h,
     chuva_72h, fonte_estacao, codigo_estacao, nome_estacao`. **Não**
     inclui `em_atencao` pré-calculado — o limiar de atenção é um slider
     no cliente, calculado em JS a partir de `chuva_24h`/`chuva_72h`.
   - **`series_<uf>.json`**: `{codigo_estacao: {nome, fonte,
     serie: [[timestamp_iso, chuva_mm], ...]}}`, recortado aos
     **últimos 30 dias** a partir da leitura mais recente disponível —
     evita um payload que cresce indefinidamente agora que o INMET
     acumula o ano inteiro (ingestão incremental).
   - **`meta_<uf>.json`**: `{gerado_em (ISO, UTC), referencia (ISO, UTC
     — a mesma que `calcular_cruzamento` usa), total_setores,
     total_estacoes_inmet, total_estacoes_ana}`.
4. Se `chuva_ana` não existir localmente, exporta normalmente só com
   INMET (mesmo comportamento hoje do `calcular_cruzamento(chuva_ana=None)`).

Reaproveita `storage.ler_setores`/`ler_chuva` e `config.caminho_setores`/
`caminho_chuva`/`caminho_chuva_ana` sem modificá-los.

## CLI (`src/cli.py`)

- Novo comando `exportar-dashboard --uf SP` (padrão de saída:
  `docs/dashboard/data/`, sobrescrevível com `--saida`).
- `atualizar` ganha uma etapa a mais (exportação), com o mesmo padrão
  try/except tolerante a falha isolada, acumulando em `falhas` — a
  exportação falhar não derruba CPRM/INMET/ANA nem vice-versa. Roda
  **depois** das três ingestões, já que depende dos dados delas.

## Frontend estático (`docs/dashboard/index.html`, novo)

HTML/CSS/JS puro — sem framework, sem build step, sem dependência do
bundle de componentes da landing page (`_ds_bundle.js`/`x-import`/
`DCLogic`). Reaproveita só os **tokens CSS** já existentes em
`docs/_ds/.../tokens/{colors,typography,spacing,shape,fonts}.css` via
`<link>`, garantindo consistência visual com a landing page sem acoplar
ao runtime dela.

**Bibliotecas externas via CDN** (sem instalação/build): Leaflet (mapa,
mesma engine que o Folium já usa por baixo) e Chart.js (gráfico de série
temporal).

**Layout** — barra de filtros fina no topo (município, janela 24h/72h,
limiar de atenção) sempre visível; abaixo, cards de métrica (total de
setores, grau alto, grau muito alto, em atenção); mapa em destaque
(Leaflet, GeoJSON colorido por grau de risco, tooltip com município,
setor, distância, chuva na janela selecionada, fonte da estação); abaixo,
lado a lado, a tabela de "setores em atenção" e o gráfico de série
temporal da estação selecionada.

**Estado e filtragem**: tudo client-side em JS puro, sobre o GeoJSON já
carregado — trocar o filtro de município, a janela ou o limiar não faz
nenhuma requisição nova, só re-renderiza o mapa/cards/tabela a partir dos
dados em memória.

**Selo de atualização**: lê `meta_<uf>.json` e mostra "atualizado em
<data>" e a data de referência da chuva — mesma informação que o
Streamlit mostra hoje, sem o botão de atualizar.

## Publicação (`.github/workflows/atualizar-dados.yml`)

Depois de `scripts/atualizar_dados.py` (que passa a incluir a exportação),
o workflow faz um commit automático de `docs/dashboard/data/*.json`/
`*.geojson` de volta no repositório (`git config` de bot + `git commit`
condicional a haver mudança + `git push`), além de continuar publicando o
artefato do GitHub Actions como hoje. Sem mudança na configuração de
Pages do repositório.

## Limpeza

- Remove `src/dashboard/app.py` e `tests/test_dashboard.py`.
- Remove `streamlit`, `streamlit-folium`, `folium`, `plotly` de
  `pyproject.toml` (`dependencies`).
- Atualiza `README.md`: seção "Uso" (troca "3. Rodando o dashboard" por
  instruções de abrir o site estático / rodar `exportar-dashboard`
  localmente), "Arquitetura" (Mermaid + menção a `src/export/` e
  `docs/dashboard/`), "Testes e CI" (contagem de testes, já que
  `test_dashboard.py` some e um `test_dashboard_data.py` novo entra),
  screenshots (as três imagens atuais de `docs/screenshots/` refletem o
  Streamlit antigo — trocar por novas do site estático, ou remover as
  referências até haver novas capturas).

## Testes

`tests/test_dashboard_data.py` (novo, mesmo padrão de HTTP mockado onde
aplicável — aqui não há rede envolvida, só leitura de arquivos locais em
`tmp_path`): cobre a exportação com INMET só, com INMET+ANA combinados
(setor usando fonte ANA aparece com `fonte_estacao="ana"` no GeoJSON), o
recorte de 30 dias na série temporal, e o conteúdo do `meta_<uf>.json`.

## Fora de escopo

- Não implementa seletor de UF/Ano no frontend (fixo em SP por ora,
  conforme decisão 3).
- Não muda a configuração de Pages do repositório (decisão 8).
- Não gera novas capturas de tela do site estático como parte deste
  spec — fica como follow-up manual depois que o dashboard estiver no ar.
- Não adiciona testes de UI/JS (sem framework de teste de frontend no
  projeto hoje) — a validação do frontend é manual (abrir o HTML,
  conferir mapa/filtros/gráfico).
