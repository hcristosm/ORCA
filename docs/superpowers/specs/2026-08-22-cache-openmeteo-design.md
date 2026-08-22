# Cache local incremental para a Open-Meteo — design

Data: 2026-08-22

## Contexto

Desde a paralelização da exportação nacional (`4564cea`, 21/08/2026), runs de
produção mostraram UFs faltando no dashboard de forma recorrente (19-20 de 27
UFs com sucesso, mesmo com ajustes sucessivos no rate limiter — espaçamento
mínimo, teto de concorrência). Investigação nesta sessão (22/08/2026) achou a
causa raiz num issue do repositório oficial da Open-Meteo
(open-meteo/open-meteo#1650): a camada gratuita permite **só 1 requisição em
voo por IP**; acima disso a requisição é enfileirada internamente, e mais de
5 na fila vira `429 Too many concurrent requests`. Isso já foi corrigido
separadamente (`max_concorrentes=1` em `src/ingest/rate_limiter.py`).

Com concorrência real limitada a 1, o pipeline nacional (27 UFs, milhares de
pontos de grade, ~30 dias de histórico por ponto) só é viável em tempo
razoável se o volume total de chamadas cair — daí este design: uma camada de
cache local que evita rebuscar dado que não muda mais.

Hoje só o caminho INMET/ANA tem cache em disco (`src/storage.py`, parquet). O
caminho Open-Meteo (fonte padrão do dashboard) é 100% ao vivo, documentado
explicitamente assim em `src/ingest/openmeteo.py`. Esse design fecha essa
lacuna.

Efeito colateral desejado: quando uma UF ainda assim esgotar os retries numa
execução, o dashboard pode servir o último dado bom cacheado daquela UF (com
indicação de idade) em vez de excluí-la do seletor — mitiga o sintoma
original ("estado sumiu") mesmo nos casos em que o cache não evita a falha.

## Componentes

### 1. Schema e módulo de cache (`src/storage/cache_openmeteo.py`)

Uma tabela SQLite, chave primária composta:

```
cache_horario(lat REAL, lon REAL, variavel TEXT, data_hora TEXT, valor REAL, buscado_em TEXT)
PRIMARY KEY (lat, lon, variavel, data_hora)
```

- `lat`/`lon` arredondados a uma precisão fixa **própria do cache** (ex.: 4
  casas decimais, ~11m no equador) — decisão que precisa ser independente do
  tamanho de célula de `src/processing/grade_espacial.py`, porque aquele é
  recalibrado a cada execução (`calibrar_tamanho_celula`, busca binária
  sobre o conjunto de pontos daquela execução) e o centro de célula do
  "mesmo" ponto físico pode deslocar levemente de uma execução para outra
  conforme a calibração muda. Se a chave do cache seguisse a grade
  recalibrada, o cache perderia hit rate por causa da própria calibração
  variar, não por o dado ter mudado de verdade. Arredondar lat/lon a uma
  precisão fixa, decidida uma vez e nunca recalculada, evita esse problema.
- `variavel`: `"chuva_mm"` ou `"vento_rajada_kmh"` — mesmo par usado em
  `src/ingest/openmeteo.py` hoje.
- `data_hora`: timestamp UTC da hora, ISO 8601 (`YYYY-MM-DDTHH:00:00Z`).
- `valor`: nullable (a Open-Meteo já retorna `null` para algumas horas; o
  cache precisa preservar isso, não confundir "sem dado" com "não
  cacheado").
- `buscado_em`: quando essa linha foi escrita, só para exibição de idade do
  dado no front-end e depuração — não participa da lógica de TTL em si (que
  é por natureza da hora, não por idade da escrita).

API do módulo (usada por `src/ingest/openmeteo.py`, não pelo resto do
pipeline diretamente):

- `horas_faltantes(pontos, variavel, horas_pedidas) -> dict[ponto, list[hora]]`
  — para cada ponto, quais horas pedidas ainda não estão cacheadas.
- `gravar(pontos_horas_valores: Iterable[tuple[ponto, hora, valor]]) -> None`
  — upsert em lote.
- `ler(pontos, variavel, horas_pedidas) -> dict[ponto, dict[hora, valor]]`
  — o que já está cacheado, para montar a série sem rebuscar.

Se o arquivo do cache estiver ausente, corrompido ou ilegível na abertura, o
módulo trata como cache vazio (loga um warning, não levanta exceção) — nunca
derruba a exportação por causa do cache.

### 2. Busca incremental em `src/ingest/openmeteo.py`

Antes de montar um lote para POST, `_fetch_variavel_batch` consulta o cache
por `(ponto, variável, hora)` para o intervalo pedido:

- Horas mais antigas que a janela "sempre expira" (últimas ~3h + toda a
  previsão) e já presentes no cache **não** entram no pedido.
- Pontos cujas horas pedidas estão 100% cacheadas e frescas são removidos do
  lote inteiramente — no limite, um lote pode gerar zero chamadas.
- Para pontos que ainda precisam de dado, o `dias_historico` do POST deixa
  de ser a constante fixa atual (30 para setor, 4 para vento) e passa a ser
  calculado por lote: o maior intervalo entre "agora" e a hora mais recente
  já cacheada entre os pontos daquele lote (com a constante atual como teto,
  para pontos nunca vistos). Depois da 1a execução que povoa o cache,
  execuções seguintes (cadência diária) só precisam pedir ~1-2 dias de
  histórico por ponto, não os 30 de novo.
- Resposta bem-sucedida grava todas as horas retornadas no cache antes de
  devolver a série para quem chamou (setor ou município), incluindo a ponta
  recente/previsão (que será sobrescrita na próxima execução, mas serve de
  fallback se aquela próxima execução falhar).

### 3. Sincronização entre execuções do workflow

O GitHub Actions runner é efêmero — nada sobrevive entre execuções sem
persistência explícita. Decisão: o cache viaja junto com os dados já
publicados no branch `gh-pages` (mesmo padrão adotado em `ee9031f` para o
dashboard), não numa branch/cache separada.

`.github/workflows/atualizar-dados.yml` ganha:

- Um passo **antes** de "Rodar atualização nacional": baixa
  `cache/openmeteo.sqlite` do `gh-pages` (se existir) para o caminho local
  esperado pelo módulo de cache. Ausência do arquivo (1a execução) não é
  erro — o módulo já trata isso como cache vazio.
- Um passo **depois**: publica o arquivo atualizado de volta para
  `gh-pages`, junto com o resto dos dados do dashboard (mesmo commit/push).
- `concurrency:` no nível do workflow (agrupado por nome do workflow,
  `cancel-in-progress: false`), para impedir duas execuções (agendada +
  manual) escrevendo o cache ao mesmo tempo — a última a publicar apagaria
  silenciosamente o progresso da outra. Esse mesmo mecanismo também evita a
  disputa de cota entre runs simultâneos observada em 22/08/2026.

### 4. Uso local (fora do CI)

`src/storage/cache_openmeteo.py` não sabe nada sobre CI/gh-pages — só abre um
arquivo SQLite num caminho configurável (default `data/cache/openmeteo.sqlite`,
gitignored, mesmo diretório de outros artefatos gerados localmente). Quem
roda o projeto localmente ganha o cache automaticamente pelas suas próprias
execuções repetidas, sem nenhum passo extra de sincronização — decisão
explícita de não replicar a complexidade de download/upload do gh-pages para
o caso local, que não tem o mesmo problema de efemeridade.

### 5. Dashboard: idade do dado por UF (efeito colateral do cache)

Quando uma UF esgota os retries mesmo depois das duas passadas de
`exportar_nacional` (ver `src/export/nacional.py`), a exportação passa a
poder servir o cache como fallback de última instância para aquela UF
(dado mais velho que o normal, mas presente) em vez de excluí-la do
`ufs_disponiveis.json`. O metadado da exportação (`meta_<uf>.json`) ganha um
campo indicando se aquela UF usou fallback de cache e a idade do dado mais
velho usado, para o front-end sinalizar isso ao usuário (ex.: badge "dado de
X horas atrás"). Este item específico (fallback visível no front-end) fica
detalhado no plano de implementação, não é bloqueante para o restante do
design.

## Testes

- Módulo de cache: testes unitários de `horas_faltantes`/`gravar`/`ler` com
  SQLite em arquivo temporário (`tmp_path`) — cobrir cache vazio, cache
  parcial (algumas horas presentes), valores `null` preservados, e abertura
  de arquivo corrompido/ausente degradando para cache vazio sem exceção.
- `_fetch_variavel_batch`: teste com cache pré-populado via monkeypatch/fake
  do módulo de cache, verificando que (a) pontos 100% cacheados não geram
  POST, (b) `dias_historico` efetivo do POST reflete o maior buraco entre os
  pontos do lote, (c) resposta da API é gravada no cache antes de retornar.
- Integração leve (`test_export_nacional.py`): 2 execuções sequenciais de
  `exportar_nacional` sobre o mesmo `tmp_path`/cache, verificando que a 2a
  execução faz menos chamadas HTTP que a 1a para o mesmo conjunto de
  UFs/período (usando `responses` para contar `calls`).
- Workflow: sem framework de teste de CI no projeto hoje; verificação manual
  rodando o workflow 2x seguidas e conferindo (via log) que a 2a execução
  reporta menos requisições que a 1a, e que o arquivo de cache aparece
  publicado em `gh-pages`.

## Fora de escopo (fica para depois, se necessário)

- Orquestração mais robusta de requisições (paginação inteligente, fila de
  jobs para espaçar envio) — decisão explícita de tratar como subprojeto
  separado, depois desta camada de cache (ver roadmap do `README.md`,
  22/08/2026). O cache reduz o volume de chamadas necessárias; a
  orquestração lida com como as chamadas restantes são enviadas ao longo do
  tempo — são preocupações independentes o suficiente para specs separadas.
- Confirmação com a Open-Meteo sobre tier gratuito ampliado para projetos
  open-source/open-access (oferecido pelo mantenedor no issue #485) — vale a
  pena tentar em paralelo, mas não é bloqueante pra este design.
- Front-end exibindo idade do dado por UF (item 5 acima) — fica detalhado no
  plano de implementação.
