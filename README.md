<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/orca-logo-escuro.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/logo/orca-logo-claro.png">
  <img src="docs/logo/orca-logo-claro.png" alt="Logo do ORCA: uma orca saltando sobre uma onda, com uma montanha, um ícone de alerta e uma gota de chuva" width="320">
</picture>

# ORCA
*Open Risk and Catastrophe Aggregator*

**Setores de risco geológico da CPRM/SGB cruzados com chuva recente do INMET, da ANA e da Open-Meteo, num dashboard estático.**

[![Release](https://img.shields.io/github/v/release/hcristosm/ORCA)](https://github.com/hcristosm/ORCA/releases/latest)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](#instalação)
[![Dashboard ao vivo](https://img.shields.io/badge/dashboard-ao%20vivo%20no%20GitHub%20Pages-c0472f)](https://hcristosm.github.io/ORCA/dashboard/)
[![CI](https://github.com/hcristosm/ORCA/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Licença](https://img.shields.io/badge/licença-BSD%203--Clause-blue)](LICENSE)

![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-150458?logo=pandas&logoColor=white)
![Leaflet](https://img.shields.io/badge/Leaflet-199900?logo=leaflet&logoColor=white)
![Chart.js](https://img.shields.io/badge/Chart.js-FF6384?logo=chartdotjs&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)

</div>

---

## Sobre

ORCA baixa a setorização de risco geológico publicada pela **CPRM/SGB** (Serviço
Geológico do Brasil), cruza cada setor com a **chuva horária mais recente
disponível publicamente** e sinaliza, num mapa interativo, quais setores estão
com chuva acumulada acima de um limiar configurável.

Nasceu de um problema concreto. Como geólogo que já mapeou áreas de risco pelo
Ministério das Cidades (PMRR de Itaquaquecetuba/SP) e que hoje trabalha com
visão computacional para monitoramento de encostas, eu queria uma ferramenta
local, sem backend, sem custo, que juntasse duas fontes públicas que raramente
aparecem lado a lado.

**Dashboard ao vivo:** [hcristosm.github.io/ORCA/dashboard](https://hcristosm.github.io/ORCA/dashboard/),
publicado no GitHub Pages e atualizado todo dia pelo cron (ver
[Atualização automática](#4-atualização-automática)).

<p align="center">
  <img src="docs/screenshots/dashboard-claro.png" alt="Dashboard do ORCA em tema claro: mapa de setores de risco geológico coloridos por grau, cards de contagem, tabela de setores em atenção e gráfico de série temporal de chuva" width="49%">
  <img src="docs/screenshots/dashboard-escuro.png" alt="Mesmo dashboard do ORCA em tema escuro" width="49%">
</p>

---

## Sumário

- [Fontes de dados](#fontes-de-dados)
- [Arquitetura](#arquitetura)
- [Instalação](#instalação)
- [Uso](#uso)
  - [1. Baixar os setores de risco (CPRM/SGB)](#1-baixar-os-setores-de-risco-cprmsgb)
  - [2. Baixar a chuva (INMET)](#2-baixar-a-chuva-inmet)
  - [3. Abrir o dashboard](#3-abrir-o-dashboard)
  - [4. Atualização automática](#4-atualização-automática)
- [Limitações conhecidas](#limitações-conhecidas)
- [Testes e CI](#testes-e-ci)
- [Decisões e investigações](#decisões-e-investigações)
- [Roadmap](#roadmap)
- [Contribuindo](#contribuindo)
- [Licença](#licença)

---

## Fontes de dados

| Fonte | O que fornece | Endpoint confirmado em 05/08/2026 |
|---|---|---|
| [**CPRM/SGB**](https://www.sgb.gov.br/) | Polígonos de setorização de risco geológico (grau de risco, tipologia, nº de moradias/pessoas afetadas) | `https://geoportal.sgb.gov.br/server/rest/services/gestaoterritorial/risco/FeatureServer/0` (ArcGIS REST, GeoJSON) |
| [**INMET**](https://portal.inmet.gov.br/) | Chuva horária por estação meteorológica automática | `https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip` (CSV, pacote público anual) |
| [**ANA**](https://www.gov.br/ana/pt-br) | Chuva em intervalos de 15min por estação telemétrica (fonte complementar ao INMET; nem toda estação tem dado vivo, ver [Decisões e investigações](#decisões-e-investigações)) | `https://telemetriaws1.ana.gov.br/ServiceANA.asmx` (SOAP/XML, sem captcha/autenticação) |
| [**Open-Meteo**](https://open-meteo.com/) | Chuva e rajada de vento horárias por coordenada (consulta direta no centro de cada setor, sem estação; **fonte padrão do dashboard exportado**) | `https://api.open-meteo.com/v1/forecast` (POST em lote, sem captcha/autenticação) |

A CPRM foi renomeada para **SGB**. Os domínios do enunciado original
(`geoportal.cprm.gov.br`, `sace.cprm.gov.br`, `arcgisserver.cprm.gov.br`) ainda
respondem parcialmente, mas a camada de setorização de risco hoje mora em
`geoportal.sgb.gov.br`, sob o certificado TLS de `geoportal.sgb.gov.br`.

## Arquitetura

```mermaid
flowchart LR
    CPRM[("CPRM/SGB<br/>ArcGIS REST")] --> ING1["src/ingest/cprm.py"]
    INMET[("INMET<br/>ZIP anual")] --> ING2["src/ingest/inmet.py"]
    ANA[("ANA<br/>rede telemétrica")] --> ING3["src/ingest/ana.py"]
    OM[("Open-Meteo<br/>por coordenada")] --> ING4["src/ingest/openmeteo.py"]
    ING1 --> STORE["src/storage/<br/>GeoPackage + CSV"]
    ING2 --> STORE
    ING3 --> STORE
    STORE --> PROC["src/processing/cruzamento.py<br/>estação mais próxima (INMET+ANA) + chuva 24h/72h"]
    PROC --> PREV["src/processing/previsao.py<br/>trajetória de alerta previsto (72h)"]
    PROC --> EXPORT["src/export/dashboard_data.py<br/>fonte openmeteo (padrão) ou inmet"]
    PREV --> EXPORT
    ING4 --> EXPORT
    EXPORT --> DASH["docs/dashboard/<br/>HTML/JS estático (Leaflet + Chart.js)"]
```

`src/cli.py` expõe os comandos de ingestão e exportação (`ingest-cprm`,
`ingest-inmet`, `ingest-ana`, `exportar-dashboard`, `atualizar`) usados
manualmente ou pelo cron diário
([`atualizar-dados.yml`](.github/workflows/atualizar-dados.yml)), que também
comita os dados exportados de volta no repositório para o GitHub Pages
publicar. `tests/` cobre cada módulo com HTTP mockado, sem depender de rede.

A camada `src/storage/` do plano original chegou a ficar de fora (SQLite/DuckDB
pareciam desnecessários para o volume de dados de um estado). Hoje ela existe
como uma camada fina sobre GeoPackage (setores) e CSV (chuva), usada por
`ingest`, `processing` e pela exportação estática, sem introduzir dependência
de banco.

`src/processing/` tem dois módulos: `cruzamento.py` (cruzamento espacial:
setor → estação mais próxima, e chuva acumulada observada) e `previsao.py`
(projeção temporal: trajetória do acumulado de 72h combinando chuva
observada e prevista pela Open-Meteo). `dashboard_data.py` consome os dois só
pela interface pública de cada um.

O dashboard já foi um app Streamlit (`src/dashboard/app.py`); foi substituído
por um site estático (`docs/dashboard/`) para resolver estética, layout e
distribuição sem processo Python rodando, ver
[Decisões e investigações](#decisões-e-investigações).

## Instalação

Requer Python 3.11+.

```bash
git clone https://github.com/hcristosm/ORCA
cd ORCA
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Uso

### 1. Baixar os setores de risco (CPRM/SGB)

```bash
python -m src.cli ingest-cprm --uf SP
# -> data/risco_sp.gpkg
```

Qualquer UF do Brasil funciona (a camada é nacional). O projeto começou por SP
mas generaliza sem mudar código.

### 2. Baixar a chuva (INMET)

```bash
python -m src.cli ingest-inmet --uf SP --ano 2026
# -> data/chuva_sp_2026.csv
```

O primeiro download baixa o ZIP anual completo do Brasil (~55MB) e mantém em
cache local (`data/inmet_<ano>.zip`); downloads seguintes para outras UFs do
mesmo ano reaproveitam o cache.

### 3. Abrir o dashboard

O dashboard é um site estático: HTML/CSS/JS puro, sem framework, sem build
step e sem processo Python rodando pra servir a interface. Ele lê arquivos
`docs/dashboard/data/*.geojson`/`*.json` gerados pela exportação abaixo.

```bash
python -m src.cli exportar-dashboard --uf SP
# fonte padrão: Open-Meteo, consulta direta por setor (sem estação)
# -> docs/dashboard/data/setores_sp.geojson, series_sp.json, meta_sp.json
# (com --fonte openmeteo, também gera previsao_sp.json, trajetória de alerta previsto)

scripts/rodar_dashboard.sh
# depois abra http://localhost:8000/dashboard/
# (ou `python -m http.server 8000 --directory docs`, o script é só um atalho)
```

(Servir por HTTP local é necessário porque o `fetch()` do navegador não lê
`file://` para os arquivos de dados; não precisa de nada além da biblioteca
padrão do Python.) Em produção, o mesmo `docs/dashboard/` é publicado pelo
GitHub Pages, com os dados atualizados diariamente pelo cron (ver abaixo).

Visualmente, o dashboard segue a linguagem "cartografia editorial": fundo de
papel com tinta escura, tipografia serifada nos títulos (Source Serif 4,
self-hosted), terracota como única cor de alarme, ícones de linha fina
(Lucide) e mapa base CARTO nos tons do tema ativo. Tema claro/escuro
acompanha a preferência do sistema por padrão, com um botão sol/lua no
header para trocar manualmente; a escolha fica salva no navegador.

Por padrão a exportação usa a **Open-Meteo** (`--fonte openmeteo`): chuva
consultada direto no centro de cada setor, sem depender de estação nem de
`ingest-inmet`/`ingest-ana` terem rodado, só precisa dos setores (CPRM). Pra
usar o cruzamento por estação mais próxima (INMET+ANA) como antes, passe
`--fonte inmet` (precisa de `ingest-inmet` já ter rodado para a UF/ano).

O mapa (Leaflet) mostra os setores coloridos por grau de risco; os filtros de
município, janela de acumulado (24h/72h) e limiar de atenção ficam numa barra
fixa no topo e recalculam tudo no navegador, sem nova requisição. Abaixo do
mapa: cards de contagem, a tabela de setores em atenção e o gráfico (Chart.js)
de série temporal, por município com a fonte Open-Meteo, por estação
(INMET/ANA) com `--fonte inmet`. Um selo no topo mostra a data de geração dos
dados, a referência da chuva e qual fonte foi usada.

Sem seletor de UF/Ano por enquanto: os dados de hoje cobrem só SP.

O mapa também traz uma camada de **rajada de vento**, desligada por padrão;
liga pelo controle de camadas no canto superior direito ("Rajada de vento").
Ligada, ela mostra um choropleth: o polígono de cada município de SP que teve
rajada relevante nas últimas 24h aparece preenchido, colorido pela severidade
em três faixas (atenção, perigo, grande perigo) derivadas de uma escala
Beaufort simplificada; passar o mouse num polígono mostra o nome do
município, o valor em km/h e a faixa. A cobertura é todos os 645 municípios
de SP, não só os que têm setor de risco geológico da CPRM. Os contornos
municipais vêm da malha territorial pública do IBGE, buscada ao vivo pelo
navegador na primeira vez que a camada é ligada, não é pré-computada nem
versionada no repositório. Como o limiar de chuva, essa escala é ilustrativa:
não é um critério oficial brasileiro calibrado para risco geológico, só uma
referência de leitura rápida.

Abaixo do dashboard oficial, a seção **"Minhas áreas"** deixa qualquer visitante carregar um arquivo
geolocalizado próprio (GeoJSON, KML ou shapefile em `.zip`) e ver chuva acumulada (24h/72h) e a
trajetória de alerta previsto (72h) calculadas para essa área, útil porque a setorização da
CPRM/SGB não é exaustiva. Tudo roda no navegador do visitante: o arquivo é parseado localmente, o
centróide da geometria é calculado com Leaflet e a chuva é buscada direto na Open-Meteo, sem passar
por nenhum servidor do ORCA. Nada do que é enviado é salvo em lugar nenhum, nem em `localStorage`,
nem no repositório; a página some tudo ao recarregar. Limite de 5 áreas por vez e 10MB por arquivo.
Como a CPRM não avaliou essas áreas, não há grau de risco geológico inferido, só um campo opcional
para o próprio visitante informar uma classificação (sinalizada como autodeclarada, não oficial).

### 4. Atualização automática

```bash
python scripts/atualizar_dados.py --uf SP --ano 2026
```

Roda as ingestões (CPRM/SGB, INMET, ANA) e a exportação dos dados do
dashboard em sequência, tolera a falha de uma fonte sem derrubar as outras e
grava `data/ultima_atualizacao.txt`. É o mesmo script que
[`atualizar-dados.yml`](.github/workflows/atualizar-dados.yml) roda todo dia
(cron `0 9 * * *`, mais `workflow_dispatch` manual): publica os dados como
artefato do GitHub Actions **e** comita `docs/dashboard/data/*` de volta no
repositório, para o GitHub Pages publicar a versão atualizada do dashboard.

## Limitações conhecidas

- **A chuva do INMET tem alguns dias de defasagem.** O pacote histórico anual
  não é atualizado minuto a minuto; a "chuva acumulada" mostrada no dashboard
  é sempre relativa à leitura mais recente **disponível**, não necessariamente
  a "agora". O próprio dashboard mostra essa data de referência.
- **A ingestão do INMET é incremental, não por data no servidor.** O INMET só
  oferece o ZIP anual completo: não há como baixar só um intervalo de datas
  do servidor (confirmado por `HEAD` real: `Range`/`ETag` suportados, mas
  cada estação tem um único arquivo cobrindo o ano inteiro). A partir da
  segunda execução, o download pula quando o ZIP não mudou (GET condicional)
  e o reprocessamento local pula estações sem mudança via CRC32, mesclando
  só os últimos 7 dias das que mudaram (janela de retificação). Retificações
  do INMET fora dessa janela de 7 dias não são recapturadas, ver
  `src/ingest/inmet.py`.
- **Densidade de estações é baixa.** SP tem 40 estações automáticas do INMET
  para 904 setores de risco; a distância média até a estação mais próxima
  fica em torno de 26km (máximo observado: ~74km). Chuva muito localizada
  (comum em eventos convectivos) pode não ser capturada pela estação mais
  próxima de um setor específico.
- **O limiar de atenção (padrão 100mm/72h) é ilustrativo.** É uma referência
  comum na literatura de risco de deslizamento, não um valor oficial calibrado
  para os setores da CPRM/SGB. O próprio dashboard avisa isso e deixa o valor
  livremente ajustável.
- **A camada de vento é observação recente, sem previsão.** Diferente da
  chuva (que tem trajetória de alerta previsto para os próximos 3 dias), a
  rajada de vento mostrada é só a máxima observada nas últimas 24h; não há
  projeção futura de vento no momento. Consumir os avisos oficiais do INMET
  diretamente (em vez de derivar severidade da Open-Meteo) é uma evolução
  possível, fora do escopo desta fase.
- **Cobertura nacional é parcial por design.** O MVP cobre SP; a arquitetura
  já generaliza para qualquer UF (ambos os clientes aceitam `--uf`), mas
  cobrir o Brasil inteiro de uma vez não fazia parte do escopo desta fase.
- **Sem autenticação/multiusuário.** É uma ferramenta local de portfólio, não
  um serviço multiusuário.
- **O dashboard estático não atualiza sob demanda.** Diferente do antigo botão
  "Baixar/atualizar dados agora" do Streamlit, o site estático só mostra os
  dados da última exportação, que roda uma vez por dia pelo cron. Pra ver
  dados mais recentes na hora, rode `exportar-dashboard` localmente (ver
  [Uso](#3-abrir-o-dashboard)).
- **A Open-Meteo tem rate limit sensível ao volume de coordenadas × dias
  pedidos, não só à frequência de chamadas.** Testado com requisições reais
  em 10/08/2026: um único `POST` com as ~900 coordenadas de SP funcionou
  isoladamente, mas repetir esse volume (ou pedir 30 dias de histórico de
  uma vez para todos os setores) gera `HTTP 429` de forma consistente: a
  API despacha "tente de novo em um minuto", e às vezes leva mais que isso
  pra liberar de fato. `src/ingest/openmeteo.py` já divide as consultas em
  lotes de 50 pontos com pausa entre eles, usa uma janela de histórico
  menor (4 dias) para o cruzamento por setor, e espera 60s especificamente
  em `429`, mas uma sessão de testes intensa (como o desenvolvimento desta
  função) pode esgotar a cota do dia/hora e fazer a exportação real falhar
  temporariamente. O cron roda uma vez por dia, bem dentro do uso normal.

## Testes e CI

```bash
pytest
```

73 testes cobrindo: parsing de resposta ArcGIS REST (CPRM/SGB), paginação,
retry com backoff e fallback para cache local; parsing do CSV do INMET,
leitura de estação dentro do ZIP anual, GET condicional do ZIP (ETag/304) e
a ingestão incremental por CRC32 (estação sem mudança pulada, estação
mudada mesclada, retificação dentro da janela de 7 dias; a fusão em si,
`_mesclar_serie_estacao`, também é testada isoladamente como função pura,
sem precisar montar ZIP/HTTP); parsing do XML/SOAP da ANA, retry em HTTP 429
e o filtro de estações sem dado recente; parsing em lote da Open-Meteo,
divisão em lotes e retry; a lógica de cruzamento espacial (estação mais
próxima, incluindo o pareamento combinado INMET+ANA com desempate por
recência) e temporal (chuva acumulada 24h/72h); a trajetória de alerta
previsto (`src/processing/previsao.py`); e a exportação dos dados do
dashboard nas duas fontes (GeoJSON de setores, recorte de 30 dias na série
temporal, metadados). Toda chamada de rede é mockada, então a suíte roda sem
internet. O dashboard em si (HTML/JS estático) não tem testes automatizados:
não há framework de teste de frontend no projeto, a validação é manual.

O workflow [`ci.yml`](.github/workflows/ci.yml) roda essa suíte a cada push e
pull request, separado do cron diário de atualização de dados.

## Decisões e investigações

Duas decisões técnicas importantes já foram investigadas com requisições
reais, não por suposição; histórico completo em
[`docs/investigacoes.md`](docs/investigacoes.md).

**CEMADEN → INMET.** O plano original previa usar o CEMADEN como fonte de
chuva, mas o download exige captcha e as únicas camadas sem captcha são
espelhos estáticos de 2017/2019. A alternativa (API dinâmica do INMET) está
atrás de um WAF que bloqueia clientes não navegador. A solução viável foi o
pacote histórico anual do INMET, usado hoje pelo ORCA. →
[detalhes completos](docs/investigacoes.md#cemaden--inmet-por-que-a-fonte-de-chuva-mudou)

**Investigação da ANA → integração feita.** A rede telemétrica da ANA foi
avaliada como fonte complementar de chuva em tempo real: das 437 estações
listadas para SP, 271 (62%) têm dado vivo, com distância mediana de 18,6km
até o setor de risco mais próximo; cobertura mais densa que o INMET.
Ressalva: as estações com dado vivo são majoritariamente
hidrelétricas/fluviométricas, não pluviômetros dedicados. A integração foi
implementada em `src/ingest/ana.py`: o cruzamento (`calcular_cruzamento`)
agora usa a estação mais próxima entre INMET e ANA combinadas: distância
manda, com desempate por recência de leitura quando as duas fontes têm uma
estação a menos de 500m de diferença de distância. →
[detalhes completos](docs/investigacoes.md#investigação-fontes-de-chuva-em-tempo-real)

**Streamlit → dashboard estático.** O dashboard começou como um app
Streamlit. Ele resolvia o problema funcional, mas tinha estética genérica
(chrome padrão do Streamlit), layout pouco customizável e não dava pra
distribuir como site; precisava de um processo Python rodando. A solução foi
pré-computar o cruzamento (`src/export/dashboard_data.py`) como
GeoJSON/JSON estáticos e servir um dashboard em HTML/CSS/JS puro
(`docs/dashboard/`), publicado no GitHub Pages e atualizado pelo cron diário.
→ [detalhes completos](docs/investigacoes.md#streamlit--dashboard-estático)

**Open-Meteo como fonte padrão do dashboard.** O INMET tem dias de
defasagem; a proposta foi testar uma fonte de chuva quase em tempo real. A
Open-Meteo (`https://api.open-meteo.com/v1/forecast`) responde chuva
horária por coordenada, sem conceito de estação; dá pra consultar
diretamente o centro de cada setor de risco. Testado com requisições reais:
funciona bem, mas tem rate limit sensível ao volume (coordenadas × dias de
histórico pedidos), não só à frequência; `src/ingest/openmeteo.py` divide
em lotes pequenos e trata `HTTP 429` especificamente. Vira a fonte padrão
da exportação (`--fonte openmeteo`); o cruzamento por estação (INMET/ANA)
continua disponível via `--fonte inmet`. →
[detalhes completos](docs/investigacoes.md#open-meteo-como-fonte-padrão-do-dashboard)

## Roadmap

- ~~Levantar quais estações da rede telemétrica da ANA têm dado vivo de chuva
  em SP e integrar como fonte complementar ao INMET~~: levantamento feito em
  08/08/2026, integração (`src/ingest/ana.py` + cruzamento combinado)
  implementada em 09/08/2026 (ver
  [Decisões e investigações](#decisões-e-investigações)).
- Fallback municipal: camadas próprias de prefeituras em ArcGIS REST, sem
  reescrever o pipeline de ingestão.
- Cobrir mais UFs além de SP (inclui trazer de volta um seletor de UF no
  dashboard estático, hoje fixo em SP).

## Contribuindo

Issues, PRs e sugestões são bem-vindos. Veja o
[guia de contribuição](CONTRIBUTING.md) para o fluxo de setup, testes e
padrão de commits, e o [Código de Conduta](CODE_OF_CONDUCT.md) que rege a
participação no projeto.

## Licença

Distribuído sob a licença [BSD 3-Clause](LICENSE): uso, cópia, modificação e
redistribuição são livres, inclusive comerciais, desde que o aviso de
copyright e a licença sejam mantidos e o crédito ao autor original
(Mateus Hcristos Leptokarydis) seja preservado.

Os dados públicos usados pertencem aos seus respectivos órgãos/serviços:
[CPRM/SGB](https://www.sgb.gov.br/), [INMET](https://portal.inmet.gov.br/),
[ANA](https://www.gov.br/ana/pt-br) e [Open-Meteo](https://open-meteo.com/);
consulte os termos de uso de cada um antes de redistribuir.
