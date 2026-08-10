# Open-Meteo como fonte de chuva do dashboard

Data: 2026-08-10

## Contexto

O dashboard estático usa a chuva do INMET (defasagem de dias) e, quando
disponível, da ANA (rede telemétrica, cobertura parcial via estação mais
próxima). O objetivo é testar o funcionamento do dashboard com uma fonte de
chuva de menor defasagem: [Open-Meteo](https://open-meteo.com/), uma API
gratuita que devolve chuva horária **por coordenada** (lat/lon), não por
estação — ou seja, dá pra consultar diretamente o centro de cada setor de
risco, sem precisar do conceito de "estação mais próxima".

## Investigação (10/08/2026, requisições reais)

- `POST https://api.open-meteo.com/v1/forecast` com `latitude`/`longitude`
  como arrays JSON (não `GET` com query string — um teste com 904
  coordenadas via `GET` bateu em `HTTP 414 URI Too Long`) aceita **todas as
  904 coordenadas dos setores de SP numa única requisição**: ~2,1s de
  resposta, 2,86MB de payload para `past_days=4`. Não precisa paginar/
  dividir em lotes para o volume atual do projeto.
- `timezone` não pode ser enviado como string simples no corpo do POST
  (a API exige array, um valor por coordenada); a solução mais simples é
  omitir o parâmetro — a API responde em `GMT`, equivalente a UTC.
- `past_days` (testado até 4, documentado até 92) e `hourly=precipitation`
  cobrem o que o projeto precisa: chuva horária recente por ponto.

## Decisões confirmadas com o usuário

1. **Substituir a fonte do dashboard, não o código já existente.**
   `src/ingest/inmet.py`, `src/ingest/ana.py` e o cruzamento por estação
   mais próxima continuam existindo e funcionando exatamente como hoje —
   só o que alimenta a exportação do dashboard muda.
2. **Cálculo por setor é direto, não por estação mais próxima.** Cada
   setor de risco é consultado no seu próprio centroide; não há conceito
   de distância real a uma estação.
3. **O gráfico de série temporal usa granularidade por município (~102
   pontos em SP), não por setor (904).** Ter 904 itens no seletor do
   gráfico não seria usável; o cruzamento por setor (mapa, tabela, chuva
   24h/72h) continua com a granularidade total pedida.
4. **Open-Meteo vira a fonte padrão do dashboard publicado** (cron diário
   e GitHub Pages), não só uma opção manual de teste.

## `src/ingest/openmeteo.py` (novo)

Sem armazenamento local incremental — diferente do INMET/ANA, o Open-Meteo
é uma API de baixo custo por consulta (confirmado: ~2s para todos os
setores de SP numa chamada só), então não há motivo para CSV acumulado,
manifesto ou cache de ZIP. Toda consulta é ao vivo, no momento da
exportação.

- `OpenMeteoFetchError` (exceção de domínio, mesmo padrão dos outros
  clientes de ingestão).
- `fetch_precipitacao_batch(pontos: list[tuple[float, float]], dias_historico: int = 30, timeout: float = 60.0, max_retries: int = 3, backoff_factor: float = 2.0, session=None) -> list[pd.DataFrame]`:
  faz um único `POST` para `https://api.open-meteo.com/v1/forecast` com
  `latitude`/`longitude` (arrays na mesma ordem de `pontos`),
  `hourly=["precipitation"]`, `past_days=dias_historico`,
  `forecast_days=1` (garante que a hora mais recente disponível entra na
  janela; horas futuras à consulta são descartadas depois, no cálculo do
  acumulado, filtrando por `data_hora <= agora`). Retry/backoff no mesmo
  formato de `_get_com_retry` dos outros clientes. Retorna uma lista de
  DataFrames (`data_hora, chuva_mm`), um por ponto de entrada, na mesma
  ordem — parseados da resposta em lista (um objeto por coordenada, cada
  um com `hourly.time`/`hourly.precipitation`).
- `dias_historico=30` como padrão único (em vez de dois valores diferentes
  para cruzamento e gráfico): a chamada por setor só usa a cauda dos
  últimos dias para o acumulado de 24h/72h, mas reaproveitar a mesma
  janela do gráfico evita manter duas constantes. O payload maior (30 dias
  vs. 4) é só tráfego de rede transitório — nunca é persistido em disco ou
  git, só usado em memória para calcular os números finais.

## Cálculo por setor (`src/export/dashboard_data.py`)

Nova função interna (ex.: `_calcular_chuva_openmeteo(setores, janelas=(24, 72), dias_historico=30) -> gpd.GeoDataFrame`):

1. Centroide de cada setor na projeção métrica já usada por
   `cruzamento.py` (`CRS_METRICO`), reprojetado de volta para
   EPSG:4326 para virar `(lat, lon)`.
2. `fetch_precipitacao_batch` com todos os centroides de uma vez.
3. Para cada setor, acumula chuva 24h/72h a partir da própria série,
   reaproveitando `_chuva_acumulada` (já existe em
   `src.processing.cruzamento`, importada em vez de duplicada).
   Referência = agora (UTC), ou o timestamp mais recente com dado
   não-nulo disponível, o que for mais cedo.
4. Monta o `GeoDataFrame` de saída com as **mesmas colunas** que
   `calcular_cruzamento` produz — `num_setor, munic, grau_risco,
   distancia_km, chuva_24h, chuva_72h, fonte_estacao, codigo_estacao,
   nome_estacao` — preenchendo `distancia_km=0.0`,
   `codigo_estacao="openmeteo"`, `nome_estacao="Open-Meteo (centro do
   setor)"`, `fonte_estacao="openmeteo"`. Mesmo schema de sempre: `
   _exportar_setores`/`PROPRIEDADES_SETOR` em `dashboard_data.py` não
   precisam mudar.

## Série temporal por município (gráfico)

Segunda função interna (`_series_openmeteo_por_municipio(setores, dias_historico=30) -> dict`):

1. Um ponto representativo por município: centroide médio (na projeção
   métrica) dos setores daquele município — não precisa de `dissolve`,
   média dos centroides já é suficiente para escolher um ponto de
   consulta razoável.
2. Uma segunda chamada a `fetch_precipitacao_batch` com os ~102 pontos de
   município.
3. Monta o mesmo formato de `series_<uf>.json` já usado hoje
   (`{chave: {nome, fonte, serie: [[iso, mm], ...]}}`), recortado aos
   últimos `JANELA_SERIE_DIAS` (30) dias — chave é o nome do município em
   vez de código de estação, `fonte="openmeteo"`.

## `exportar_dashboard` (`src/export/dashboard_data.py`)

Ganha um parâmetro `fonte: str = "openmeteo"` (valores `"openmeteo"` ou
`"inmet"`):

- `fonte="inmet"`: comportamento **idêntico ao atual**, sem nenhuma
  mudança — lê `chuva_inmet`/`chuva_ana`, chama `calcular_cruzamento`.
  Só precisa dos dados do INMET (e ANA, se existir) já ingeridos
  localmente, como hoje.
- `fonte="openmeteo"` (novo padrão): só precisa dos **setores** (CPRM já
  ingerido) — não depende de `ingest-inmet`/`ingest-ana` terem rodado.
  Chama as duas funções novas acima. `OpenMeteoFetchError` é convertida
  em `ExportacaoDashboardError` (mesma exceção que o resto do módulo já
  levanta), para não precisar mudar o tratamento de erro no CLI.
- `meta_<uf>.json` ganha um campo `"fonte": "inmet" | "openmeteo"`. Com
  `fonte="openmeteo"`, os campos `total_estacoes_inmet`/
  `total_estacoes_ana` somem e entra `"total_municipios"` no lugar.

## CLI (`src/cli.py`)

- `exportar-dashboard` ganha `--fonte [openmeteo|inmet]`, **padrão
  `openmeteo`**.
- `atualizar` ganha o mesmo `--fonte`, também padrão `openmeteo`,
  repassado para a chamada de `exportar_dashboard`. **Continua rodando
  CPRM, INMET e ANA como hoje** mesmo quando `fonte=openmeteo` — os dados
  incrementais desses dois continuam sendo mantidos vivos, só não
  alimentam mais a exportação por padrão. Isso é intencional: permite
  comparar/voltar para `--fonte inmet` a qualquer momento sem precisar
  reingerir nada.
- Sem comando novo de ingestão para o Open-Meteo — não há o que
  persistir localmente.
- Falha do Open-Meteo (`ExportacaoDashboardError`) já cai na mesma
  tolerância que a etapa de exportação já tem em `atualizar` (não
  crítica, não derruba o job) — nenhuma mudança adicional de tratamento
  de erro necessária ali.

## Frontend (`docs/dashboard/index.html`)

Dois ajustes pequenos, sem mudar estrutura:

- O selo do topo passa a mostrar "Fonte: Open-Meteo (consulta direta por
  setor)" quando `meta.fonte === "openmeteo"`, em vez da contagem de
  estações INMET/ANA.
- O tooltip do mapa esconde a linha "Estação a Xkm" quando
  `fonte_estacao === "openmeteo"` (distância sempre seria 0, não agrega
  informação nesse caso).

## Testes

- `tests/test_openmeteo.py` (novo): parsing da resposta em lote (lista de
  objetos, um por coordenada), retry em falha transitória, erro após
  esgotar tentativas — HTTP mockado com `responses`, sem depender de
  rede.
- `tests/test_dashboard_data.py`: novos casos para `fonte="openmeteo"` —
  `distancia_km=0.0`/`codigo_estacao="openmeteo"`/`fonte_estacao=
  "openmeteo"` no GeoJSON exportado, `series_<uf>.json` com chaves de
  município, `meta_<uf>.json` com `"fonte": "openmeteo"` e
  `"total_municipios"`. Caso de regressão: `fonte="inmet"` continua
  produzindo exatamente o que produz hoje.

## Fora de escopo

- Não implementa paginação/lotes para o Open-Meteo — o volume atual (SP,
  904 setores) cabe numa única requisição; se um UF muito maior no futuro
  estourar algum limite prático da API, isso é um problema para quando
  aparecer, não antecipado aqui.
- Não remove nem altera `src/ingest/inmet.py`, `src/ingest/ana.py` ou
  `src/processing/cruzamento.py` — ficam intocados, ainda cobertos pelos
  testes existentes.
- Não adiciona nenhuma UI para trocar a fonte dentro do próprio dashboard
  publicado (isso é escolhido na exportação, não no navegador).
