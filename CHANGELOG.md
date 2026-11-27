# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.

As entradas são agrupadas por tipo (`FEATURES`, `FIXES`, `REFACTOR`, `CHORE`)
e cada item usa o prefixo do commit correspondente, no padrão
[Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/).
O projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/).

Versões até a 1.0.0 usam o formato anterior, com seções
`Added`/`Changed`/`Fixed` do [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

## [Unreleased]

### CHORE
- docs(readme): seção "Para quem é", com o uso por defesa civil, pesquisa e quem desenvolve, e seção "Como citar", nas versões em português e em inglês
- chore(citation): `CITATION.cff` com autor, ORCID, licença e referência ao BELUGA, para o botão "Cite this repository" do GitHub e para o arquivamento no Zenodo

## [3.0.0] - 2026-11-27

### FEATURES
- feat(ingest): os setores de risco passam a vir da publicação v1 do [BELUGA](https://github.com/hcristosm/BELUGA), e o ORCA deixa de falar com a CPRM/SGB. São 21.429 setores em 27 UFs, de sete fontes, contra 18.908 de uma só. Entram Belo Horizonte (665 áreas sem grau, estudo de 1996), Juiz de Fora (994), Recife (364 pontos), Contagem (265 pontos), Suzano (178) e Congonhas (73): cidades que a CPRM não cobre ou cobre com dado mais antigo. `baixar-beluga` recusa, sem tocar no dado que já está no disco, contrato diferente de `v1`, manifest com menos de 27 UFs, sha256 que não bate, contagem de feições diferente da declarada e UF que viria menor que a publicação anterior do ORCA. UF que falha fica com o dado anterior, o motivo de cada falha vai para o log e o run fica vermelho sem congelar as outras 26
- feat(dashboard): o grau de risco passa a sair de uma lista única e ordenada por severidade. Antes a hachura, os contadores e a legenda tinham cada um a sua lista, e as três discordavam: setor "Médio" existia no dado, não tinha hachura, não aparecia na legenda e sumia da soma dos cards. Agora "Muito alto", "Alto", "Médio", "Baixo" e "sem grau informado" têm hachura, legenda, contador e filtro, e os cards saem das chaves presentes no recorte, então a soma fecha com o total mesmo quando aparece um valor que a interface não conhece
- feat(dashboard): ponto de risco ganha marcador próprio. Recife e Contagem mapearam imóveis e pontos, não polígonos, e um `Point` em `L.geoJSON` virava um marcador com o ícone padrão do Leaflet, que a CSP bloqueia: 629 setores ficavam invisíveis. A conta de "você está dentro do setor" também cai para proximidade de 50 metros quando a caixa do setor tem área nula, o que conserta de quebra os setores finos de Belém e Jaboatão
- feat(dashboard): cada setor mostra de onde veio. A ficha traz fonte, órgão, produto e licença; a legenda filtra por fonte do mapeamento e pela sobreposição com a CPRM; o selo de atualização nomeia as fontes daquela UF; e a aba Tutorial ganha uma seção de créditos e licenças, alcançável no computador e no celular, com o IBGE nomeado e a oferta de código-fonte da AGPL
- feat(dashboard): a contagem do cabeçalho deixa de somar duas vezes a mesma encosta. Um setor municipal que repete mais da metade da área de um setor da CPRM (`bl_cp_frac > 0.5`) fica de fora da soma, com uma linha dizendo quantos foram, clicável para filtrar só eles. Nenhum setor é escondido do mapa. O limiar de 1% do BELUGA responde "existe relação?"; este responde "é o mesmo lugar?"
- feat(relatorio): o CSV e o PDF creditam cada fonte do recorte com a sua licença, e passam a trazer `fonte_setor`, `orgao_setor`, `licenca_setor`, `sobrepoe_cprm` e `contado`. Setor sem grau aparece como "sem grau" em vez de ter a linha omitida

### FIXES
- fix(ingest): `bl_sob_cp` é booleano com nulo e atravessava três formatos virando texto ou número. Vindo do JSON, a coluna cai num `object` misto, e o pyogrio grava `object` misto como TEXTO no GeoPackage; lida de volta, coluna booleana com nulo vira `float64`. O front-end compara com `=== true`, então o arquivo saía com `"True"` (que em JavaScript é verdadeiro tanto quanto `"False"`) ou com `1.0` (que nunca é `true`). Medido na publicação v1 no ar: os 2.539 setores externos saíam todos como não sobrepostos. O tipo passa a ser convertido nos dois pontos, e os testes conferem o tipo declarado no arquivo, não o que o pandas devolve
- fix(dashboard): o selo de atualização tratava data ausente como dado fresco. A data da coleta vinha do manifesto da ingestão, e manifesto apagado (que é justamente o que se faz para forçar carga completa) deixava o selo sem data e sem aviso: a coleta podia estar parada há meses sem ninguém ver. Data ausente passa a contar como desatualizada
- fix(dashboard): o id do `<pattern>` da hachura era derivado de `grau.toLowerCase()`, o que gera `hach-médio` com acento, e o `<pattern>` se chama `hach-medio`. O polígono ficava sem preenchimento nenhum, sem erro no console e sem cair no padrão
- fix(publicacao): o escopo da mescla sai do manifest do BELUGA, e não dos GeoPackages baixados. Com a branch `dados-base`, `data/` vinha inteira em todo run e o escopo era sempre as 27 UFs; lendo do BELUGA, ele passou a ser só o que o download trouxe hoje, e uma UF com sha256 errado saía do escopo, não era preservada do `gh-pages` e fazia a guarda recusar a publicação das 27 por regressão. Falha de uma UF parava a atualização de todas as outras, e para falha determinística isso se repetiria todo dia. O mesmo valia para `workflow_dispatch` com `--ufs SP`. Medido com os dois scripts: 1 UF falha publica 27, dispatch de 1 UF publica 27, e o run degenerado de 1/27 continua recusado
- fix(publicacao): o `setores_pontos.json` passa a ser preservado da publicação anterior quando o run não o gera. Ele é nacional, a guarda conta UFs e não o enxerga, o deploy apaga do `gh-pages` o que não está em `docs/dashboard`, e `indexar-setores` é `continue-on-error` de propósito: uma falha dele tirava a tela "Perto de mim" do ar para todo mundo com o run fechando VERDE
- fix(dashboard): `escaparHtml` não escapava aspas, porque `textContent` -> `innerHTML` só cuida de `<`, `>` e `&`. O `grau_risco` do dado, que vem de sete fontes e nunca é validado campo a campo, era montado dentro de `data-filtro="..."`: uma aspa fecha o atributo e deixa injetar `onfocus=`, que a CSP da página executa por causa do `'unsafe-inline'`
- fix(dashboard): os cards por grau contavam todos os setores e o cabeçalho descontava os repetidos, então em MG o cabeçalho dizia 5.568 e a soma dos cards dava 5.692, sem nada na tela explicando a diferença. Os dois passam a sair do mesmo conjunto
- fix(ci): o cache da Open-Meteo passa a `actions/cache/restore` mais `actions/cache/save` com `!cancelled()`. O `actions/cache` de um passo só grava num post com `post-if: success()`, então o cache era descartado exatamente no dia em que uma UF falha, e o run seguinte reconstruiria frio contra a cota diária
- fix(workflow): uma UF que falha no download não congela as outras 26. A falha passou a ser por UF, e não da fonte inteira como era com a branch `dados-base`: sem `if`, o passo vermelho fazia o GitHub pular a atualização nacional e a mescla republicava o dado de ontem para as 27 UFs

### REFACTOR
- refactor(workflow)!: o `ingerir-setores.yml` e a branch `dados-base` deixam de existir, e o `atualizar-dados.yml` passa a baixar do BELUGA. O cache da Open-Meteo sai do `gh-pages` para o `actions/cache`, e com isso o site publicado deixa de carregar 68 MB de sqlite junto. O `force_orphan` fica: sem ele o `gh-pages` cresceria 6,9 MB por publicação (medido), cerca de 2,5 GB por ano num repositório de 90 MB, e o que se compraria seria um `git revert` que a reexecução do workflow já resolve
- refactor(ingest)!: saem `src/ingest/cprm.py`, os comandos `ingerir-setores` e `ingest-cprm`, os caminhos `caminho_setores` e `caminho_manifesto_cprm` e a propriedade `nome_estacao` do GeoJSON (o que ela informava já está em `distancia_km`). O GeoPackage local passa a se chamar `beluga_<uf>.gpkg`: o nome é exigência do contrato e impede que um arquivo da ingestão antiga, ainda no disco de alguém, seja lido como se fosse o novo
- refactor(dashboard)!: o bloco `cprm` do `meta_<uf>.json` vira `setores`, com `coletado_em`, `mais_recente`, `contrato` e a lista de fontes daquela UF com órgão, licença e contagem. O índice da tela "Perto de mim" sobe para a versão 2, com `bl_fonte` e `bl_produto` no fim de `campos`

### CHORE
- test(ci): os 67 casos de `tests/js/calculo.html` passam a rodar dentro do `pytest` (`tests/test_js.py`, com o Chrome do sistema via playwright). Antes só rodavam quando alguém lembrava de abrir o navegador, e esta versão pôs grau, fonte, sobreposição, índice v2 e ponto de risco dentro do `calculo.js`. Não há passo novo no CI, porque o CI já roda `pytest`, e nenhum navegador é baixado
- docs: os READMEs ficam com propósito, uso do dashboard, fontes e créditos, limitações e licença; o funcionamento técnico (pipeline, comandos, workflows, guardas e como reverter) vai inteiro para `docs/funcionamento.md`
- docs(readme): o topo dos dois READMEs troca o ícone do app por um header com a orca, o nome e curvas de nível (`docs/logo/orca-header.webp`). O ícone e o logo do app não mudam
- chore(deps): incorpora as atualizações de ruff e typer e agrupa o dependabot num PR por ecossistema, por mês
- chore(deps): `actions/cache` sobe de 4 para 6, o que também tira o aviso de descontinuação do Node 20 no run diário, e o grupo do pip incorpora typer, ruff e playwright

## [2.6.0] - 2026-11-21

### FEATURES
- feat(dashboard): logo novo, uma orca sobre fundo azul. O ícone do app ganha versões separadas para cada plataforma: `any` com cantos arredondados, `maskable` com a orca dentro do círculo seguro (antes o mesmo arquivo servia aos dois e o Android cortava as bordas) e `apple-touch-icon` de 180 px. O cabeçalho usa o ícone, que serve aos dois temas, então a troca de logo junto com o tema sai. A tela de abertura do app no Android passa a ser azul, e o README traz o logo com "ORCA" escrito embaixo. Os arquivos têm nomes novos e o cache da casca vai para `v2`, para nenhum cache prender o ícone antigo. `scripts/gerar_icones.py` refaz tudo a partir da arte de origem
- feat(dashboard): a busca acha município SEM setor da CPRM. A SGB não mapeou São Paulo, Rio, BH, Recife, Salvador, Petrópolis, São Sebastião, Guarujá e centenas de outras cidades (o mapeamento ali é de órgão estadual ou municipal), e digitar o nome não achava nada. Agora a sugestão aparece com "sem setor CPRM"; escolher leva o mapa até o município com um balão que diz que falta de setor não é falta de risco, e a tela Perto dá o veredito pela chuva no ponto central do município. A lista vem de `municipios.json`, estático e versionado (5.570 municípios do IBGE, gerado por `scripts/gerar_municipios.py`), então o dashboard não passa a depender do IBGE no ar; se o arquivo falhar, a busca fica como antes. A cobertura sai do índice nacional do dia, e só UF cuja lista carregou marca alguém como "sem setor"

### FIXES
- fix(dashboard): "Perto de mim" dizia "Este ponto não é setor mapeado pela CPRM" e "Nenhum setor mapeado pela CPRM a menos de 10 km" sem mais nada, o que em Petrópolis ou São Paulo se lê como "aqui não tem risco". As duas frases passam a dizer que a CPRM não mapeou todas as cidades e que isso não quer dizer que não há risco; a lista vazia indica o 199 da Defesa Civil
- fix(ingest): a poda incremental da CPRM apagava do GeoPackage todo setor ausente da lista de `objectid`, sem conferir o tamanho da lista. Uma lista truncada pela SGB (o corte de 2000 já visto em MG, que tem 3695) apagaria setores reais, e a guarda do `ingerir-setores.yml` só confere tamanho de arquivo, então o run fecharia verde. Agora a poda que removeria mais de 10% da UF e mais de 5 setores é recusada: a UF fica com o GeoPackage e o manifesto do mês anterior, e o job sai com 1. O piso de 5 deixa UF pequena (TO tem 9 setores) apagar um ou dois setores sem travar o mês. Remoção real e grande pede apagar o manifesto da UF para forçar carga completa
- fix(ingest): o marcador d'água da CPRM recebia o máximo só dos registros novos, então um setor reeditado com `objectid` ou `data_setor` baixo rebaixava o marcador e o mês seguinte baixava quase a UF inteira. Passa a guardar o maior entre o antigo e o novo
- fix(ingest): a paginação da CPRM não pedia ordem, e o ArcGIS não garante páginas estáveis sem ela, então a carga completa podia duplicar ou pular setores. Passa a pedir `orderByFields=objectid`

### CHORE
- docs(readme): READMEs reorganizados nos dois idiomas, com a mesma estrutura: sem a seção de decisões e investigações, sem os diagramas, sem repetições e com a falta de cobertura da CPRM nas limitações
- docs(contributing): reescrito com a prioridade de confiabilidade, a regra de publicação, os quatro gates, os testes de JS, o padrão de commits e o processo de release
- chore: `CLAUDE.md` sai do versionamento

## [2.5.0] - 2026-11-11

### FEATURES
- feat(dashboard): PWA que abre sem sinal. Um service worker guarda a casca do app (HTML, CSS, JS, fontes, ícones, bibliotecas do CDN) e o índice de setores; arquivos do próprio site vêm da rede primeiro (4 s de limite) e caem no cache sem rede, então uma versão nova chega já na primeira carga com sinal. Dados ao vivo (tiles, Open-Meteo, INMET, radar, raios) não passam pelo cache. Sem rede, "Perto de mim" mostra a última consulta com a hora. A sonda da recarga de aba parada passa direto pelo service worker, para não recarregar sem sinal
- feat(dashboard): tela "Perto de mim", a primeira no celular. Com a localização do aparelho, dá o veredito do ponto (Risco iminente, Alerta previsto em ~Nh, Sem alerta ou Sem dado agora) e lista até 5 setores da CPRM a menos de 10 km, com distância, direção e estado. Ponto fora de setor é tratado como setor pela chuva, com o aviso de que não é área mapeada. Tudo no aparelho: índice estático e uma só chamada à Open-Meteo. Sem GPS, usa o centro do município buscado; sem Open-Meteo, o ponto fica em "Sem dado" e os setores usam o valor publicado com a hora; sem índice, só o veredito do ponto; sem rede, a última consulta guardada com a hora. Tocar num setor abre o mapa com o cartão dele
- feat(export): índice nacional leve de setores (`setores_pontos.json`: código, UF, município, grau, centroide, caixa e chuva publicada), gerado por `python -m src.cli indexar-setores` num passo próprio do workflow diário, depois da mescla com o gh-pages, para cobrir também as UFs preservadas da véspera. São 18.908 setores em ~520 KB com gzip, contra 49 MB dos GeoJSON por UF. O passo usa `continue-on-error`: falhar não bloqueia a publicação, e não toca em `ufs_disponiveis.json` nem na guarda
- feat(dashboard): no mapa do celular, tocar a até 24 px de um setor abre um cartão com município, código, grau, chuva da janela, limiar e a resposta em texto (acima do limiar, passa do limiar por volta de tal hora, ou abaixo e sem previsão de passar). Antes, o detalhe era um tooltip de mouse e a mediana dos setores tinha 2 px na tela. Setor perto do dedo ganha do popup do aviso do INMET. O cartão vai no link (`s=`), tem Compartilhar e Rota até aqui, e fecha arrastando para baixo. Desktop mantém o tooltip
- feat(dashboard): casca do celular (abaixo de 768 px). Barra fina com busca e botão de ajustes no topo; abas Perto, Mapa, Alertas e Mais embaixo; mapa ocupando a tela; gaveta com Estado, Critério, Janela, régua do limiar e camadas como interruptores. Os controles existentes são movidos, não clonados, e voltam ao lugar no desktop, que fica idêntico. A aba vai no link (`v=`); link antigo com município abre no Mapa, e o app aberto sem link abre em Perto. Fechar a gaveta pelo Voltar do Android não desfaz o critério escolhido nela
- feat(dashboard): seletor "Critério" no cabeçalho, ao lado da Janela, com os limiares da literatura que antes só existiam como botões dentro da aba Tutorial (Santos 80mm/72h, Tamoios 100mm/72h, PPDC-SP 120mm/72h, Rio 125mm/24h, BH 70mm/72h). As opções nascem dos próprios botões da tabela, então não há uma segunda lista para sair de sincronia; pares repetidos aparecem uma vez só. Mexer no slider ou na janela à mão volta o seletor para "Personalizado"
- feat(dashboard): limiar e janela vão no link (`#/<uf>/<município>?l=80&j=72`), então o link compartilhado abre com a mesma régua. Mexer no limiar ou na janela atualiza a URL com replaceState, sem encher o Voltar; Voltar/Avançar restauram o critério de cada entrada. Valor inválido na URL é ignorado ou ajustado pelo slider (0–300, passo 5)
- feat(dashboard): sem link (atalho do app instalado, endereço digitado), o dashboard reabre na última UF, município e critério, guardados no localStorage
- feat(dashboard): aba aberta há mais de 30 min recarrega sozinha depois de 5 min sem interação, e a URL devolve UF, município e critério. Não recarrega sem rede (sonda `ufs_disponiveis.json` antes) nem com áreas em "Minhas áreas", que se perderiam

### FIXES
- fix(dashboard): no celular, os controles do Leaflet flutuavam sobre o cabeçalho, a busca de município ficava com 48 px ("Bus") e 27 controles tinham menos de 44 px de toque. O mapa isola o próprio empilhamento, o cabeçalho deixa de ser fixo abaixo de 768 px, todo controle tocável passa a ter 44 px e a legenda nasce recolhida num botão "Legenda" (aberta, cobria ~38% do mapa). Desktop inalterado
- fix(dashboard): camada viva que falhava ficava em cache como ausente pelo resto da sessão, então a caixa só voltava recarregando a página. Agora só o sucesso é cacheado: a próxima montagem do mapa (troca de UF, Voltar/Avançar) tenta de novo e a camada volta sozinha quando a fonte se restabelece
- fix(dashboard): camada viva que não vinha (raios do GLM, radar da RainViewer) sumia do controle de camadas sem deixar rastro na tela -- o aviso ficava só no console, então faltava a caixa de seleção e nada dizia por quê. O controle passa a mostrar "<camada>: fonte sem dado agora" no lugar da caixa. Os dois caminhos silenciosos do GLM (resposta 200 sem quadros e quadro mais velho que o limite) também passam a avisar no console

### CHORE
- docs(dashboard): reescreve a aba Tutorial no estilo ASD-STE100 aplicado a ~80% (média de 9,6 palavras por frase), mantendo a tabela de critérios, os botões, as notas de fonte e as referências
- docs(readme): seção "No celular" nos dois READMEs, com as telas Perto de mim, cartão do setor e abertura sem sinal, e o passo a passo de instalação no Android (Chrome) e no iPhone (Safari); contagem de testes atualizada e os testes de JS documentados
- chore(deps-dev): atualiza `ruff` (>=0.17.3), `pytest` (>=9.2.0) e `mypy` (>=2.4.1)

## [2.4.0] - 2026-10-28

### FEATURES
- feat(dashboard): botão "Atualizar agora" por município: busca a chuva de UM ponto (o centro dos setores daquele município) direto da Open-Meteo, no navegador, e mostra o acumulado na janela ativa com a hora da última observação. Trocar a janela recalcula a série que já está na mão, sem nova requisição. O valor fica em bloco próprio e não entra na régua, nos contadores, nas tabelas nem nos pins: aqueles seguem a exportação diária, que consulta o ponto de grade do setor. A UF inteira ao vivo não cabe na quota de um visitante (SP são ~900 pontos de grade com 4 dias de histórico e 72h de previsão)

### FIXES
- fix(dashboard): abaixo de 1081px a `.coluna-contexto` vira `display: contents` e o `.selo` tem `order: 3`, para a procedência descer ao fim da grade; o bloco do "Atualizar agora" ficava com o `order` padrão e subia 1.532px acima do selo. Entra na mesma regra. O `.botao-exportar` é botão-texto, sem borda, então "Atualizar" colava na frase: ganha o separador `·` do selo

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
