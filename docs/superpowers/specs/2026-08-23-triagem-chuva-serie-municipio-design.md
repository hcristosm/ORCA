# Triagem por chuva prevista para a série de 30 dias por município

## Contexto

`_series_openmeteo_por_municipio` (`src/export/dashboard_data.py`) busca
`JANELA_SERIE_DIAS = 30` dias de histórico horário para **todo** município
que tem ao menos um setor de risco CPRM, independente de haver ou não chuva
relevante prevista ali. Numa execução nacional (27 UFs), isso soma ~1.596
municípios × 30 dias × 24h — a maior fatia do volume de linhas/chamadas à
Open-Meteo do pipeline (ver
`docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md`), e um fator
relevante na duração (~1h30) e na taxa de erro (HTTP 429) das execuções
recentes.

`_calcular_chuva_openmeteo` (setores, que roda antes na mesma exportação, com
`dias_historico=4`) já calcula, sem nenhuma chamada adicional à API, uma
trajetória do acumulado de chuva prevista para as próximas 72h por setor
(`previsao`, via `src.processing.previsao.trajetoria_chuva_72h`). Este design
usa esse dado, que já existe, para decidir quais municípios realmente
precisam dos 30 dias completos.

## Mecanismo

1. Em `_exportar_openmeteo` (que já chama `_calcular_chuva_openmeteo` antes
   de `_series_openmeteo_por_municipio`), agregar `previsao` por município:
   para cada município, o pico (máximo) entre os valores não nulos de todas
   as trajetórias de 72h dos setores daquele município (via a coluna
   `munic`, já presente no GeoDataFrame de setores).
2. Município cujo pico ultrapassa `LIMIAR_ATENCAO_MM_PADRAO` (100.0mm,
   `src/config.py` — mesma constante já usada por
   `src.processing.cruzamento.marcar_atencao`, reaproveitada aqui para
   manter consistência com o resto do app) entra no grupo **completo**
   (`dias_historico=JANELA_SERIE_DIAS`, 30); os demais entram no grupo
   **reduzido** (`dias_historico=DIAS_HISTORICO_CRUZAMENTO`, 4 — a mesma
   janela que os setores já usam).
3. `_series_openmeteo_por_municipio` passa a fazer até duas chamadas a
   `fetch_precipitacao_batch` (uma por grupo, pulando a chamada de um grupo
   vazio) em vez de uma, e mescla os resultados de volta por município antes
   de montar a série de saída — a forma do retorno não muda.

Nenhuma chamada nova à Open-Meteo é introduzida: o sinal de triagem é
subproduto de uma busca que já acontece. O que muda é o `dias_historico`
pedido na busca que já existia para a série por município.

## Trade-off assumido

A maioria dos municípios (tipicamente quase todos, na maioria dos dias) vai
mostrar 4 dias de histórico no gráfico do dashboard em vez de 30. Essa
mudança de produto foi discutida e aceita: o layout/navegação atual do
dashboard já está previsto para ser redesenhado à frente (item futuro de
roadmap, fora do escopo deste design), então não vale investir agora em
suavizar esse trade-off (ex.: janela intermediária, indicação visual de
"série reduzida").

## Interação com o cache incremental

Compõe sem conflito com `src/storage_cache_openmeteo.py`: o `dias_historico`
decidido aqui é só o teto pedido à API; `_dias_historico_efetivo` (em
`src/ingest/openmeteo.py`) continua livre para encolher ainda mais, caso o
cache já tenha parte desse histórico. Um município que permanece no grupo
reduzido por muitas execuções não acumula cache para a faixa de 5-30 dias
atrás (nunca foi pedida); no dia em que esse município cruzar o limiar e
entrar no grupo completo, essa faixa mais antiga não estará cacheada e será
buscada ao vivo — comportamento correto, só sem o desconto de cache para
essa faixa específica na primeira vez.

## Escopo explicitamente fora

- Camada de vento (`src/export/vento_data.py`): já usa `dias_historico=4`
  (baixo custo), não passa pela série de 30 dias — sem mudança.
- Instabilidade da API de malha municipal do IBGE (~40min perdidos numa
  execução recente, 25/27 UFs sem camada de vento): problema
  independente, tratado como item separado do roadmap.
- Redesenho do layout/navegação do dashboard: mencionado acima como
  motivação para não otimizar o trade-off do gráfico agora; fica para um
  design próprio, futuro.

## Testes

- Agregação por município: setor com pico >100mm marca o município; setor
  abaixo não marca; município com múltiplos setores usa o máximo entre eles;
  trajetória com todos os pontos `None` (sem previsão de futuro disponível)
  não marca o município.
- `_series_openmeteo_por_municipio` com municípios mistos: mock de
  `fetch_precipitacao_batch` confirmando duas chamadas, uma com
  `dias_historico=30` (só os municípios relevantes) e outra com
  `dias_historico=4` (os demais); grupo vazio não gera chamada.
- Teste de integração (`test_export_nacional.py` ou `test_dashboard_data.py`)
  ponta a ponta, verificando o `past_days` de cada chamada HTTP via
  `responses`.
