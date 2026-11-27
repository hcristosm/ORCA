# Como o ORCA funciona

Detalhe técnico: pipeline, comandos, workflows, guardas e como reverter. O
[README](../README.md) responde o que o ORCA é e como usar o dashboard.

## A ideia em uma frase

Um pipeline em Python baixa os setores de risco já prontos do
[BELUGA](https://github.com/hcristosm/BELUGA), busca a chuva de cada setor na
Open-Meteo e grava arquivos estáticos. O dashboard no navegador lê esses
arquivos. Não há servidor nem banco de dados.

## De onde vêm os setores

O ORCA não fala mais com a CPRM/SGB. Quem coleta, normaliza e valida a
setorização federal, junto com os mapeamentos estaduais e municipais, é o
BELUGA, que publica um GeoJSON por UF sob um contrato de dados versionado.

```
BELUGA v1 (GitHub Pages)  ->  baixar-beluga  ->  data/beluga_<uf>.gpkg
                                                      |
                              Open-Meteo  ->  atualizar-nacional
                                                      |
                                         docs/dashboard/data/*.{geojson,json}
                                                      |
                                              gh-pages (GitHub Pages)
```

O que o ORCA ganhou com isso: setores de Belo Horizonte, Recife, Suzano, Juiz
de Fora, Contagem e Congonhas, que a CPRM não cobre ou cobre com dado mais
antigo; e uma fonte que não cai junto com o geoportal da SGB.

### O contrato v1

`https://hcristosm.github.io/BELUGA/v1/manifest.json` é o primeiro arquivo
lido. Dele saem o número do contrato, a lista das 27 UFs, o sha256 e a
contagem de setores de cada arquivo, e a ficha de cada fonte (nome, órgão,
licença).

`baixar-beluga` recusa, sem tocar no dado que já está no disco:

| Conferência | Por que |
|---|---|
| `contrato != "v1"` | Mudança incompatível sai em `/v2/`. Ler v2 como v1 é importar dado com outro significado |
| manifest com menos de 27 UFs | Publicação parcial do lado de lá; as UFs que faltam não teriam contra o que ser comparadas |
| sha256 do arquivo recebido não bate | Download corrompido ou publicação trocada no meio |
| contagem de feições diferente da declarada | GeoJSON truncado, que é o jeito de um arquivo chegar menor sem erro de rede |
| UF com menos setores que a publicação anterior do ORCA | Publicar menos do que está no ar é proibido |

Uma UF que falha fica com o dado anterior e o comando sai com 1, nomeando o
motivo de cada falha. O run fica vermelho, mas as outras 26 UFs seguem: a
exportação pula UF sem GeoPackage sem interromper as demais.

### Colunas que vêm do BELUGA

Além das colunas da setorização (grau, tipologia, moradias, pessoas), cada
setor traz a sua proveniência. As que chegam ao dashboard:

| Coluna | Conteúdo |
|---|---|
| `bl_fonte` | Id da fonte, ex.: `br-sgb-setorizacao`, `pe-recife-sedec` |
| `bl_produto` | `setorizacao_risco`, `area_risco_sem_grau` ou `ponto_risco` |
| `bl_licenca` | Licença daquela fonte |
| `orgao_exec` | Órgão que fez o levantamento |
| `bl_sob_cp` | Se o setor se sobrepõe a algum setor da CPRM. Nulo nos setores da própria CPRM |
| `bl_cp_frac` | Fração da área coberta por setor da CPRM. Nulo quando não se aplica (pontos não têm área) |

`bl_sob_cp` é booleano com nulo. Ele atravessa GeoJSON, GeoPackage e GeoJSON
de novo, e em dois desses saltos o pandas o transforma: coluna `object` mista
vira TEXTO no GeoPackage, e coluna booleana com nulo é lida como `float64`.
Qualquer um dos dois produz `"True"` ou `1.0` no arquivo que o front-end lê, e
em JavaScript `"False"` é verdadeiro tanto quanto `"True"`. Por isso o tipo é
convertido de propósito nos dois pontos, e os testes conferem o tipo declarado
no arquivo, não o que o pandas devolve.

### Contar setor sem contar duas vezes

Um setor de fonte municipal pode cobrir a mesma encosta que um setor da CPRM.
O BELUGA marca a sobreposição a partir de 1% de área, que responde "existe
relação?". Para contar, o ORCA usa outro limiar, `LIMIAR_SETOR_REPETIDO = 0.5`
em `src/config.py`, que responde "é o mesmo lugar?".

A contagem do cabeçalho é, então, **os setores da CPRM mais os externos com
`bl_cp_frac <= 0.5`**. Os demais continuam no mapa, com a relação na ficha, e
uma linha abaixo do contador diz quantos ficaram de fora da soma. Nenhum setor
é escondido; nenhum é somado duas vezes em silêncio.

## Linha de comando

```bash
python -m src.cli baixar-beluga --ufs SP,RJ,MG          # sem --ufs = as 27
python -m src.cli atualizar-nacional --ufs SP,RJ,MG     # chuva + exportação
python -m src.cli exportar-dashboard --uf SP            # uma UF só
python -m src.cli indexar-setores --dados docs/dashboard/data
```

| Comando | Para que serve | Opções principais |
|---|---|---|
| `baixar-beluga` | Baixa, confere e grava os setores | `--ufs`, `--diretorio`, `--publicado`, `--timeout` |
| `atualizar-nacional` | Exporta várias UFs com uma grade compartilhada | `--ufs`, `--orcamento-alvo`, `--diretorio`, `--saida` |
| `exportar-dashboard` | Exporta uma UF | `--uf`, `--diretorio`, `--saida` |
| `indexar-setores` | Gera o índice leve da tela "Perto de mim" | `--dados` |

`--publicado` aponta para o `data/` do que já está no ar. É de lá que sai o
piso por UF. Sem ele, não há piso por UF.

### Variáveis de ambiente

| Variável | Efeito | Padrão |
|---|---|---|
| `ORCA_PISO_COBERTURA` | Fração mínima de UFs que uma publicação precisa ter | `0.6` |
| `ORCA_LOG_LEVEL` | Nível de log do pipeline | `INFO` |

## O orçamento da Open-Meteo

A Open-Meteo gratuita aceita 600 chamadas por minuto, 5.000 por hora e 10.000
por dia. O ORCA tem mais de 21 mil setores.

`atualizar-nacional` monta **uma** grade espacial para todo o Brasil antes de
exportar qualquer UF, e consulta a chuva no ponto de grade, não no centroide
de cada setor. O tamanho da célula é calibrado por busca binária até o total
de pontos distintos caber em `--orcamento-alvo` (padrão 6.000). Setores
vizinhos, mesmo em UFs diferentes, dividem a mesma consulta.

Isso quer dizer que **setor novo custa resolução, não cota**: os 2.521 setores
que o BELUGA acrescentou não geraram uma chamada a mais. Fora do orçamento
fica a série por município, um ponto por município com setor, que cresceu em
três (Belo Horizonte, Recife e Suzano).

`src/storage_cache_openmeteo.py` guarda a chuva já baixada, e só hora passada,
para previsão não virar chuva observada.

## Os arquivos publicados

O pipeline grava em `docs/dashboard/data/`, com nomes em minúsculas.

| Arquivo | Conteúdo |
|---|---|
| `setores_<uf>.geojson` | Setores com grau, proveniência, chuva acumulada e alerta |
| `series_<uf>.json` | Série horária de chuva por município |
| `previsao_<uf>.json` | Trajetória de alerta para as próximas 72h |
| `meta_<uf>.json` | Totais, data de referência e o bloco `setores` com as fontes daquela UF |
| `setores_pontos.json` | Índice nacional leve dos setores, para o celular |
| `ufs_disponiveis.json` | UFs publicadas. Guia o seletor de estado e a guarda |
| `versao.txt` | Id do run que publicou, para o teste de fumaça |

O `setores_pontos.json` é um contrato à parte, com `versao` e `campos`. Campo
novo entra **no fim** da lista e sobe a versão, porque `calculo.js` monta cada
registro por nome de campo. A versão corrente é a 2, com `bl_fonte` e
`bl_produto` no fim.

## Como roda em produção

Um workflow só, [`atualizar-dados.yml`](../.github/workflows/atualizar-dados.yml),
às 09:00 UTC (06:00 em São Paulo), ou à mão com `workflow_dispatch`. A ordem
dos passos importa:

1. **Cache da Open-Meteo** (`actions/cache`). A chave tem o id do run, então
   nunca dá acerto exato e o cache é salvo no fim de todo run; `restore-keys`
   restaura o mais recente. Cache ausente degrada para uma reconstrução fria,
   que é segura.
2. **Buscar o `gh-pages` e extrair o publicado** em `publicado/data`. Daqui
   saem duas coisas: a contagem publicada, que é o insumo da guarda, e o piso
   por UF do download.
3. **Baixar do BELUGA**, com as cinco conferências acima.
4. **Rodar a atualização nacional**: grade, chuva, exportação.
5. **Preservar as UFs não regeneradas** (`scripts/mesclar_publicado.py`).
6. **Gerar o índice** da tela "Perto de mim".
7. **Conferir antes de publicar** (`scripts/conferir_publicacao.py`).
8. **Publicar** no `gh-pages` e **conferir o site no ar**.

### O que protege a publicação

A spec tem um invariante: nenhuma publicação destrói dado bom. Ele se apoia em
três peças que não se substituem.

**A mescla** preserva a UF que não foi regenerada hoje. A cobertura diária
oscila entre 70% e 100%, então sumiço seria o caso comum, e a guarda viraria
uma catraca travada no melhor dia já publicado. Com a mescla, degradar vira
envelhecer: a UF que falhou continua no ar com o dado da véspera.

**O piso de cobertura da mescla** (`ORCA_PISO_COBERTURA`, 0.6) é o detector de
run degenerado. Ele precisa existir justamente porque a mescla torna
`atual >= publicado` verdadeiro por construção, e sem ele a guarda
anti-regressão passaria a aprovar qualquer run. O escopo é medido pelos
`beluga_<uf>.gpkg` em `data/`, e **escopo vazio desliga o piso**: por isso o
prefixo do arquivo é load-bearing, e há um teste amarrando-o a
`caminho_setores_beluga`.

**A guarda** (`conferir_publicacao.py`) compara o conjunto a publicar com o
que está no ar e recusa publicar menos, publicar abaixo do piso ou publicar
sem conseguir ler o que está no ar. Ela grava `publicar=false` **antes** de
sair com 1, e toda recusa sai com 1.

**O teste de fumaça** confere que a URL pública serve o deploy deste run, e
não o de ontem, pelo `versao.txt` com o id do run.

Essas regras vieram de dois runs de 2026 que apagaram o dashboard e fecharam
como `success`. Daí a regra da casa: **nunca julgue um run pelo status; confira
as contagens e o site no ar.**

### Branches

| Branch | Conteúdo |
|---|---|
| `main` | Código |
| `gh-pages` | Dashboard publicado |

O `gh-pages` tem histórico. O deploy deixou de usar `force_orphan` quando o
cache da Open-Meteo saiu de dentro do `publish_dir`, e com histórico dá para
reverter uma publicação ruim.

### Como reverter

| Situação | O que fazer |
|---|---|
| Publicação ruim no ar | `git revert` do commit no `gh-pages`, ou rodar o workflow de novo: a publicação é idempotente |
| O BELUGA publicou errado e o ORCA recusou | Nada. As UFs ficam com o dado anterior. Corrija no BELUGA e rode de novo |
| O BELUGA saiu do ar | O download falha alto e nada é publicado. O que está no ar continua |
| Uma UF encolheu de propósito | A guarda vai recusar. Republique com o escopo novo deliberadamente |

## Estrutura do repositório

```
src/                      pipeline em Python
tests/                    testes em Python (rede mockada) e testes de JS
scripts/                  guarda de publicação, mescla, geradores e atalho do dashboard
docs/dashboard/           front-end estático (publicado em gh-pages)
docs/dashboard/data/      saídas do pipeline (ignoradas pelo git)
data/                     GeoPackages locais (ignorados pelo git)
.github/workflows/        CI, atualização diária, release
.github/actions/          preparar-python e baixar-branch
```

| Módulo | O que faz |
|---|---|
| `src/cli.py` | Comandos da linha de comando (Typer) |
| `src/config.py` | **Toda** convenção de caminho e as constantes. Use `caminho_setores_beluga()` em vez de montar um caminho à mão |
| `src/ingest/beluga.py` | Download e conferência da publicação v1 do BELUGA |
| `src/ingest/openmeteo.py` | Chuva horária por coordenada, em lotes de 50 pontos |
| `src/ingest/rate_limiter.py` | Ritmo das requisições, compartilhado |
| `src/storage/` | Camada fina sobre GeoPackage. Não há banco de dados |
| `src/storage_cache_openmeteo.py` | Cache SQLite da chuva já baixada |
| `src/processing/cruzamento.py` | Centroides e chuva acumulada na janela |
| `src/processing/grade_espacial.py` | Grade adaptativa nacional |
| `src/processing/previsao.py` | Trajetória de alerta de 72h |
| `src/export/dashboard_data.py` | Exporta uma UF |
| `src/export/nacional.py` | Orquestra as 27 UFs com uma grade compartilhada |
| `src/export/indice_setores.py` | Índice nacional leve dos setores |

O front-end é JavaScript puro, sem build. O `index.html` carrega o `comum.js`
primeiro (ele expõe `window.ORCA`). Os cálculos sem DOM ficam em `calculo.js`;
a versão de celular em `movel.js` e `perto.js`; "Minhas áreas" e relatórios em
`areas-customizadas.js` e `relatorio.js`; o modo sem sinal em `sw.js`.

## Testes e gates

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src scripts
.venv/bin/python -m bandit -q -c pyproject.toml -r src scripts
```

O CI roda os quatro a cada push. Rode-os antes de commitar. Toda chamada de
rede é mockada, inclusive nos casos de falha, então a suíte roda sem internet.

Os cálculos do front-end têm testes em `tests/js/calculo.html`. Eles rodam no
navegador, porque o projeto não usa Node: sirva a raiz do repositório com
`python3 -m http.server 8001` e abra
`http://localhost:8001/tests/js/calculo.html`. A página termina com
"PASSOU n/n". O resto do dashboard é validado à mão.
