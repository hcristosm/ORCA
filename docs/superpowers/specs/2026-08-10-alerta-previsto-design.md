# Alerta previsto — usar a previsão da Open-Meteo pra antecipar setores

Data: 2026-08-10

## Contexto

O dashboard já mostra, com a fonte Open-Meteo, a chuva acumulada
**observada** em 24h/72h por setor. A Open-Meteo também devolve **previsão**
de chuva horária pros próximos dias (já usamos `forecast_days=1` na consulta
atual). A ideia é usar essa previsão pra sinalizar, com antecedência, quais
setores **ainda não estão** em atenção hoje mas devem cruzar o limiar de
72h nos próximos dias, segundo a previsão — não só reagir ao que já choveu.

## Decisões confirmadas com o usuário

1. **Métrica: janela móvel combinando passado + futuro**, não só a soma da
   chuva prevista isolada. Pra cada ponto no tempo dos próximos dias,
   calcula o que o acumulado de 72h *seria naquele momento* (chuva já caída
   + prevista até ali) — mostra uma trajetória, não um número único.
2. **Horizonte de 3 dias** (72h) à frente. Depois desse prazo a previsão de
   chuva fica pouco confiável pra esse tipo de alerta antecipado.
3. **Apresentação**: setores com alerta previsto (mas sem alerta atual)
   ganham contorno tracejado no mapa (distinto do contorno sólido de "em
   atenção" hoje) e uma seção própria na tabela, "Alerta previsto", com a
   data/hora estimada de quando cruzariam o limiar — separada da tabela de
   "Setores em atenção" (que continua só com o observado).
4. **Só com `fonte=openmeteo`.** INMET/ANA são redes de observação, sem
   previsão. Se o arquivo de previsão não existir (dashboard gerado com
   `fonte=inmet`), essa parte da UI simplesmente não aparece.

## Cliente Open-Meteo (`src/ingest/openmeteo.py`)

`fetch_precipitacao_batch` e `_post_lote` ganham um parâmetro
`dias_previsao: int = 1` (hoje o `forecast_days=1` está fixo no corpo da
requisição; vira parametrizável, com o mesmo valor padrão — nenhum
comportamento existente muda). A consulta por setor passa a pedir
`dias_previsao=3`, cobrindo o horizonte de alerta previsto; a consulta por
município (gráfico) continua com o padrão de 1 dia, sem mudança.

Isso aumenta o volume por ponto da consulta por setor de `dias_historico=4`
(passado) para `4 dias passado + 3 dias futuro = 7 dias` de série horária —
bem abaixo do volume (`30 dias`) que causou `HTTP 429` real em testes
anteriores (ver `docs/investigacoes.md#open-meteo-como-fonte-padrão-do-dashboard`).
Os lotes de 50 pontos e o tratamento de 429 já existentes continuam
valendo.

## Cálculo da trajetória (`src/export/dashboard_data.py`)

Nova função `_trajetoria_chuva_72h(serie, agora, passo_horas=3,
horizonte_horas=72) -> list[list]`: para cada ponto `t` de `agora` até
`agora + horizonte_horas` em passos de `passo_horas` (25 pontos: 0h, 3h,
6h, ..., 72h), reaproveita `_chuva_acumulada(serie, t, 72)` — a mesma
função já usada para o acumulado observado, que soma `chuva_mm` na janela
`(t - 72h, t]` independente de os dados serem passados ou futuros (é só uma
soma numa janela de tempo; a origem observada/prevista dos pontos dentro
dela já vem misturada na mesma série contínua devolvida pela Open-Meteo).
Retorna `[[timestamp_iso, mm_acumulado_previsto], ...]`.

`_calcular_chuva_openmeteo` passa a **retornar também** um dicionário de
previsão (`{num_setor: [[iso, mm], ...]}`), calculado a partir da mesma
série já buscada — **sem uma segunda consulta à API** (evita dobrar o
volume de requisições numa integração que já se mostrou sensível a rate
limit). Isso muda o tipo de retorno da função de `gpd.GeoDataFrame` para
`tuple[gpd.GeoDataFrame, dict]`; o único chamador (`exportar_dashboard`) é
atualizado junto.

## Exportação (`exportar_dashboard`)

Com `fonte="openmeteo"`, grava um quarto arquivo,
`previsao_<uf>.json` — `{num_setor: [[iso, mm], ...]}`, mesmo formato de
`_trajetoria_chuva_72h`. Com `fonte="inmet"`, esse arquivo não é gerado
(sem previsão disponível nessa fonte).

## Frontend (`docs/dashboard/index.html`)

- Busca `data/previsao_<uf>.json` além dos três arquivos já buscados —
  numa chamada separada e não-crítica: se o arquivo não existir (dashboard
  gerado com `fonte=inmet`, ou versão antiga sem esse arquivo), a seção de
  alerta previsto simplesmente não aparece, sem quebrar o resto do
  dashboard.
- Em `renderizarTudo()`: para cada setor que **não** está em
  `emAtencao` (observado), verifica sua trajetória de previsão contra
  `estado.limiar` (o mesmo slider já existente) e encontra o primeiro
  ponto em que o valor previsto cruza o limiar. Se houver, o setor entra
  numa nova lista `alertaPrevisto`, guardando o timestamp estimado.
- Mapa: setores em `alertaPrevisto` ganham contorno tracejado (cor igual à
  de "em atenção", `weight`/`dashArray` diferentes) — distinto do contorno
  sólido de quem já está em atenção hoje.
- Tabela: nova seção "Alerta previsto" abaixo de "Setores em atenção",
  colunas Município/Setor/Grau/Quando (data estimada), ordenada pelo setor
  que cruzaria o limiar mais cedo primeiro.
- Legenda do mapa ganha uma linha explicando o contorno tracejado.

## Testes

- `tests/test_openmeteo.py`: `dias_previsao` chega corretamente no corpo
  da requisição (`forecast_days`), com o padrão `1` preservando o
  comportamento atual.
- `tests/test_dashboard_data.py`: `_trajetoria_chuva_72h` calcula
  corretamente os pontos da janela móvel a partir de uma série sintética
  com chuva passada e futura conhecidas; `_calcular_chuva_openmeteo`
  retorna a tupla `(gdf, previsao)` com as chaves esperadas;
  `exportar_dashboard(fonte="openmeteo")` grava `previsao_<uf>.json`;
  `exportar_dashboard(fonte="inmet")` não grava esse arquivo.

## Fora de escopo

- Não implementa notificações/alertas ativos (e-mail, push) — só a
  sinalização visual no próprio dashboard.
- Não muda o horizonte de 3 dias nem a amostragem de 3 em 3 horas por
  configuração de usuário — são constantes no backend por ora.
- Não estende a previsão pro gráfico de série temporal por município
  (continua só com o observado, sem mudança).
