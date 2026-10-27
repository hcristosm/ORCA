# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.

As entradas são agrupadas por tipo (`FEATURES`, `FIXES`, `REFACTOR`, `CHORE`)
e cada item usa o prefixo do commit correspondente, no padrão
[Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/).
O projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Versões até a 1.0.0 usam o formato anterior, com seções
`Added`/`Changed`/`Fixed` do [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [Unreleased]

### FEATURES
- feat(dashboard): botão "Atualizar agora" por município: busca a chuva de UM ponto (o centro dos setores daquele município) direto da Open-Meteo, no navegador, e mostra o acumulado na janela ativa com a hora da última observação. Trocar a janela recalcula a série que já está na mão, sem nova requisição. O valor fica em bloco próprio e não entra na régua, nos contadores, nas tabelas nem nos pins: aqueles seguem a exportação diária, que consulta o ponto de grade do setor. A UF inteira ao vivo não cabe na quota de um visitante (SP são ~900 pontos de grade com 4 dias de histórico e 72h de previsão)

### REFACTOR
- refactor(dashboard): `fetchComTimeout`, `buscarChuvaOpenMeteo`, `chuvaAcumulada` e `referenciaObservada` passam a morar em `comum.js` (`window.ORCA`), em vez de cópias no `index.html` e em `areas-customizadas.js`. "Minhas áreas" ganha de graça o timeout de 8s que as camadas do mapa já tinham

### CHORE
- chore(ci): o workflow diário passa a apagar os deployments antigos do environment `github-pages`, mantendo só o do run atual (eram 127 entradas acumuladas na página do repo). A API exige marcar `inactive` antes do DELETE. O passo roda depois do teste de fumaça, quando o deployment deste run já existe, e é `continue-on-error`: limpeza cosmética não derruba a publicação

## [2.3.2] - 2026-10-26

### FIXES
- fix(dashboard): as camadas de raios (RealEarth/GLM) e de radar (RainViewer) usavam `fetch` sem timeout. Host que *pendura* não rejeita o `fetch`: a promessa nunca assentava, a camada não entrava no controle e o `.catch` não rodava, então nada aparecia no console. Reproduzido com o `realearth.ssec.wisc.edu` fora do ar (000 em 10s): a camada de raios sumia em silêncio. As duas passam a usar o `fetchComTimeout` do próprio arquivo, com 8s, como o INMET

### CHORE
- docs(readme): reescreve os dois READMEs no estilo ASD-STE100 aplicado a ~80% (frases curtas, voz ativa, um termo por conceito; média de 11 palavras por frase) e acrescenta o diagrama Mermaid da publicação, a leitura do dashboard, a estrutura do repositório, a referência da CLI, o contrato dos arquivos do dashboard, as variáveis de ambiente e as branches

## [2.3.1] - 2026-10-24

### FIXES
- fix(openmeteo): o cache gravava as horas de previsão junto com as observadas, e um run diário que falhasse transformava previsão em chuva "medida" no acumulado de 72h (reproduzido: 117 mm onde não choveu). Agora só grava hora já passada, e o cache publicado é descartado uma vez (`PRAGMA user_version`)
- fix(openmeteo): resposta com menos itens que pontos era aceita e desalinhava pontos e séries (um município recebia o gráfico de outro); HTTP 200 com HTML escapava como `JSONDecodeError`. As duas são validadas dentro do retry
- fix(openmeteo): timeout e 5xx esperavam o backoff segurando o único slot de concorrência e congelavam todas as UFs; só o 429 (limite por IP) espera segurando o slot, de propósito
- fix(openmeteo): hora gravada como `null` no cache nunca era rebuscada
- fix(openmeteo): caminho do cache saía do diretório de execução, não de `config.py`, e ignorava `--diretorio`
- fix(nacional): exceção fora de uma lista fechada (ex.: `KeyError` por mudança de schema da CPRM, GeoPackage corrompido) numa UF derrubava a exportação das 27
- fix(cli): erro inesperado numa UF interrompia a ingestão mensal das UFs seguintes
- fix(cprm): erro do ArcGIS com HTTP 200 não era retentado
- fix(cprm): carga completa vazia (HTTP 200 sem features) gravava um GeoPackage de 0 setores e um manifesto de sucesso, que passavam pelo limiar de 10 KiB do workflow
- fix(cprm): a ingestão incremental nunca removia setores apagados ou renumerados na fonte (agora poda pelos `objectid` vivos, via `returnIdsOnly`), e um manifesto sem GeoPackage salvava só os setores novos
- fix(publicacao): `workflow_dispatch` com `ufs` nunca publicava; o piso de cobertura agora é medido contra as UFs pedidas (`--pedidas`)
- fix(dashboard): o mapa reenquadrava a cada movimento do slider, da janela ou dos filtros, jogando fora o zoom do usuário
- fix(dashboard): na janela de 24h, setor com 72h acima e 24h abaixo do limiar sumia de "Em atenção" e de "Alerta previsto"
- fix(dashboard): falha de rede ou JSON inválido deixava o selo em "Carregando dados…" para sempre
- fix(dashboard): os filtros de grau da legenda não faziam nada no choropleth
- fix(dashboard): áreas customizadas usavam sempre 72h para "Em atenção", ignorando o seletor de janela
- fix(dashboard): o download do CSV revogava o blob logo após o clique, e a impressão do relatório dependia de um `onload` que podia já ter passado

### REFACTOR
- refactor(export): remove a mescla com o `meta_<uf>.json` anterior, que só servia ao extinto bloco `vento` e derrubava a UF quando o arquivo antigo estava corrompido
- refactor(nacional): remove `tamanho_celula_grade_graus` e `total_celulas_grade`, que nunca chegavam ao meta (o dado continua no log da exportação)

### CHORE
- chore(deps-dev): atualiza `ruff` e `setuptools`

## [2.3.0] - 2026-10-23

### FEATURES
- feat(dashboard): lista de avisos do INMET no painel, com filtro de abrangência (esta UF, macrorregião do IBGE ou Brasil) e de dia (hoje, amanhã e os próximos dias com aviso); a camada do mapa segue o mesmo recorte, a busca tem timeout e a fonte fora do ar vira um estado próprio no bloco, distinto de "nenhum aviso"

### FIXES
- fix(dashboard): `aviso_cor` vinda da API do INMET ia crua para atributo `style` e para o Leaflet; `escaparHtml` serializa via `textContent` e não escapa aspas duplas. Agora passa por validação de hex, e a severidade virou tarja (o amarelo oficial do "Perigo Potencial" era ilegível como texto no tema claro)
- fix(dashboard): resposta 200 com corpo inesperado da API do INMET era tratada como "zero avisos"; um `.gov.br` fora do ar responde 200 com HTML de portal

## [2.2.0] - 2026-10-20

### FEATURES
- feat(dashboard): instalável como app (PWA)

### FIXES
- fix(dashboard): tira INMET/ANA da atribuição de chuva
- fix(cprm): lê `data_setor` em milissegundos, não como 01/01/1970
- fix(dashboard): teto de zoom do radar e dos raios conforme o que as fontes servem

### CHORE
- chore: relicencia de BSD 3-Clause para AGPL-3.0-or-later — versões distribuídas ou oferecidas como serviço pela rede precisam publicar o código-fonte sob a mesma licença; até a v2.1.0 continua BSD 3-Clause
- chore(deps): atualiza `mypy`, `ruff`, `shapely` e `typer`

## [2.1.0] - 2026-10-17

### FEATURES
- feat(dashboard): aba Tutorial — como ler a régua e o limiar, limiares de referência (Defesa Civil de Santos, Concessionária Tamoios, PPDC-SP, sirenes do Rio, Petrópolis, Belo Horizonte, Tatizana et al.) com fontes, e botões "Usar Xmm/Yh" que aplicam o critério na régua

## [2.0.0] - 2026-10-13

### FEATURES
- feat(dashboard): layout de dashboard em altura de tela — três colunas com rolagem própria (contexto, mapa, painel), "Minhas áreas" como aba e o mapa sempre à vista; abaixo de 1081px tudo empilha como antes
- feat(dashboard): toolbar de ícones no mapa (voltar ao estado, enquadrar, tela cheia) e pin nos setores acima do limiar e em alerta previsto, com clique para descer ao município
- feat(dashboard): legenda e contadores filtram o mapa por classe (grau, acima do limiar, alerta previsto); as contagens e a tabela seguem as do recorte inteiro
- feat(dashboard): camada opcional de raios (GOES-19 GLM via SSEC RealEarth) no mapa — raio total, não ponto de impacto; omitida se a fonte cair ou o quadro tiver mais de 30 min
- feat(dashboard): camada de avisos meteorológicos oficiais do INMET no mapa (polígono, cor da severidade, riscos e instruções no popup), filtrada pela UF selecionada
- feat(ci): teste de fumaça pós-deploy em `atualizar-dados.yml` — espera a URL pública servir o deploy do run (marcador `versao.txt`) e confere a contagem de UFs no ar
- feat(dashboard): selo de atualização por fonte (CPRM/SGB e chuva), em horário de Brasília, com idade do dado e alerta de desatualizado
- feat(dashboard): navegação pela URL (`#/<uf>/<município>`) com Voltar/Avançar do navegador, links compartilháveis, botão "Voltar ao estado" e trilha clicável
- feat(dashboard): busca de município em todo o Brasil, com sigla da UF; escolher uma cidade de outro estado troca a UF e seleciona a cidade
- feat(dashboard): camada opcional de radar de chuva (RainViewer) no mapa
- feat(export): `meta_<uf>.json` ganha os blocos `cprm` (`ingerido_em`, `setor_mais_recente`) e `chuva` (`fonte`, `ate`, `consultado_em`)
- feat(export): `meta_<uf>.json` ganha a lista `municipios`, índice da busca nacional

### FIXES
- fix(dashboard): `[hidden]` perdia para o `display` das regras de layout e a vista escondida continuava na tela
- fix(cprm): ingestão incremental sem setores novos não quebra mais com `ValueError`
- fix(dashboard): recriar o mapa durante a animação de zoom não lança mais `_leaflet_pos`
- fix(dashboard): busca não sobrescreve mais as primeiras teclas digitadas logo após escolher uma sugestão
- fix(dashboard): CSP bloqueava o radar do RainViewer; ajustes de cor e zoom da camada
- fix(dashboard): radar RainViewer saía em tons de cinza (herdava o filtro do basemap); agora usa pane própria

### REFACTOR
- refactor(ingest)!: remove as trilhas INMET e ANA (módulos, comandos `ingest-inmet`/`ingest-ana`, opção `--fonte`, cruzamento por estação mais próxima). Nenhum workflow as executava desde que a exportação diária virou nacional; a Open-Meteo passa a ser a única fonte de chuva
- refactor(cli)!: remove o comando `atualizar` e o parâmetro `--ano` de `exportar-dashboard`/`atualizar-nacional`, que só existiam para a fonte INMET
- refactor(ci): extrai `.github/actions/baixar-branch` e `.github/actions/preparar-python`, eliminando três cópias do bloco de fetch de branch e três do setup de Python
- refactor(ci): a guarda anti-regressão dos dois workflows vira `scripts/conferir_publicacao.py`, com teste cobrindo as duas propriedades da recusa
- refactor(ci): `atualizar-dados.yml` chama `python -m src.cli atualizar-nacional` direto; `scripts/atualizar_dados.py` (só um shim) foi removido
- refactor(dashboard): `escaparHtml` e `token` saem das três cópias para `comum.js` (`window.ORCA`)

### CHORE
- chore(deps): atualiza `ruff` de >=0.14.0 para >=0.16.9
- chore(deps): atualiza `geopandas` de >=1.1.4 para >=1.2.0
- chore(deps): remove `defusedxml`, que só era usado pelo parser XML da ANA

## [1.1.0] - 2026-09-12

### FEATURES
- feat(dashboard): exportação de relatórios em CSV e PDF, 100% client-side — em lote na tabela de setores da CPRM (respeitando filtro de UF e limiar ativo), por linha individual e nos cards de área customizada
- feat(dashboard): ícones de download e impressão no sprite, no mesmo estilo Lucide dos demais

### REFACTOR
- refactor(ingest): remove duplicação em metadados de estação, série temporal e retry de requisições
- refactor(processing): extrai helpers de cruzamento e centroides
- refactor(export): simplifica cache de leitura e montagem dos dados do dashboard

### FIXES
- fix(readme): corrige o link da release, que apontava para o destino errado

### CHORE
- chore(deps): atualiza `typer`, `mypy`, `bandit`, `setuptools`, `responses` e `softprops/action-gh-release`

## [1.0.0] - 2026-08-29

Primeira versão estável: pipeline de ingestão nacional (27 UFs), dashboard
estático publicado via GitHub Pages e gates de qualidade (testes, lint,
tipos, segurança) reforçados em CI.

### Added
- `ruff`, `mypy` e `bandit` como gates de qualidade, rodando em CI a cada push/PR.
- Empacotamento formal (`build-system`/wheel e sdist via `python -m build`), publicado como artefato da release no GitHub.

### Changed
- Parsing de XML da ANA migrado para `defusedxml`, eliminando a superfície de ataque de expansão de entidade.
- Tipagem reforçada em `dashboard_data`, `cprm`, `openmeteo` e `ana` (retornos, parâmetros de requisição e narrowing de `Optional`).

### Fixed
- Ajuste de `fillOpacity` na visualização de nível de risco do dashboard.

## [0.4.0] - 2026-08-24

### Added
- Cobertura nacional: ingestão e exportação para as 27 UFs (`atualizar-nacional`), com grade espacial adaptativa compartilhada entre UFs.
- Ingestão incremental da CPRM/SGB via marcador d'água (`objectid`/`data_setor`), rodando mensalmente em branch própria e isolada do pipeline diário.
- Cache SQLite incremental para a Open-Meteo, sincronizado entre execuções de CI via `gh-pages`, reduzindo o volume de requisições repetidas.
- Camada de vento por município (choropleth via malha do IBGE) e depois removida junto com a dependência do IBGE (ver "Removed").
- Triagem de municípios por chuva forte prevista, agregada à série de 30 dias no dashboard.
- Publicação não destrutiva do dashboard: guardas anti-regressão que recusam publicar um run degenerado (queda no total de UFs, piso de cobertura inválido) e alarme por defasagem em vez de cobertura simples.
- Seletor de UF no dashboard, dados guiados por `ufs_disponiveis.json`.
- `CONTRIBUTING.md` e Código de Conduta (Contributor Covenant).
- CSP no dashboard e Dependabot configurado no repositório.

### Changed
- Job diário de ingestão passa a ler os setores de risco de `dados-base` em vez de consultar a SGB diretamente, reduzindo carga na fonte externa.
- Rate limiter da Open-Meteo ajustado (espaçamento entre requisições, `max_concorrentes` reduzido) após confirmação do limite real do serviço.
- UFs que falham na primeira passada são reexportadas em série numa segunda passada.

### Fixed
- Diversas correções de robustez no pipeline nacional: orçamento de tempo honesto, pacing entre UFs, publicação parcial, normalização de resposta de lote de 1 ponto da Open-Meteo.
- Correções de estado obsoleto no dashboard ao trocar de UF (malha/nomes do IBGE, listeners, município selecionado).

### Removed
- Camada de vento e dependência do IBGE.

## [0.3.0] - 2026-08-11

### Added
- Painel de áreas customizadas: upload de GeoJSON/KML/shapefile pelo visitante, com cálculo de acumulado de chuva e trajetória prevista para a área desenhada.
- Redesenho visual do dashboard: tema cartográfico editorial (claro/escuro), tipografia própria (Source Serif 4, self-hosted), ícones Lucide.
- Screenshots do dashboard ao vivo e link do GitHub Pages no README.

### Changed
- Licença BSD 3-Clause adicionada ao projeto.

## [0.2.0] - 2026-08-10

### Added
- Ingestão da rede telemétrica da ANA como fonte de chuva complementar ao INMET, combinada por regra de distância/recência.
- Ingestão incremental do INMET por estação, com download condicional de ZIP e manifesto de CRC32 por estação.
- Cliente Open-Meteo para chuva por coordenada, adotado como fonte padrão de chuva do dashboard.
- Alertas previstos: trajetória rolante de 72h calculada a partir da previsão de chuva, exibida por setor no dashboard.
- Dashboard reescrito de Streamlit para site estático HTML/JS.

### Fixed
- Diversas correções de revisão pós-implementação nas features de ingestão ANA/INMET e alertas previstos (retry/backoff, tratamento de erro, consistência de horizonte de alerta).

## [0.1.0] - 2026-08-05

### Added
- Primeira versão do ORCA: dashboard local de risco geológico x chuva, cruzando setores de risco da CPRM/SGB com dados de chuva do INMET.
