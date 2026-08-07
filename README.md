<div align="center">

# ORCA
*open source risk and catastrophe aggregator*

**Setores de risco geológico da CPRM/SGB cruzados com chuva recente do INMET, num dashboard local.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](#instalação)
[![Streamlit](https://img.shields.io/badge/dashboard-streamlit-ff4b4b)](#rodando-o-dashboard)
[![CI](https://github.com/hcristosm/ORCA/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)
[![Licença](https://img.shields.io/badge/uso-portfólio-lightgrey)](#licença)

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

<p align="center">
  <img src="docs/screenshots/dashboard-mapa.png" alt="Mapa de setores de risco geológico coloridos por grau de risco, com filtros na barra lateral" width="100%">
</p>

---

## Sumário

- [Fontes de dados](#fontes-de-dados)
- [O que mudou em relação ao plano original](#o-que-mudou-em-relação-ao-plano-original)
- [Arquitetura](#arquitetura)
- [Instalação](#instalação)
- [Uso](#uso)
  - [1. Baixar os setores de risco (CPRM/SGB)](#1-baixar-os-setores-de-risco-cprmsgb)
  - [2. Baixar a chuva (INMET)](#2-baixar-a-chuva-inmet)
  - [3. Rodar o dashboard](#3-rodando-o-dashboard)
  - [4. Atualização automática](#4-atualização-automática)
- [Limitações conhecidas](#limitações-conhecidas)
- [Testes e CI](#testes-e-ci)
- [Roadmap](#roadmap)
- [Licença](#licença)

---

## Fontes de dados

| Fonte | O que fornece | Endpoint confirmado em 05/08/2026 |
|---|---|---|
| **CPRM/SGB** | Polígonos de setorização de risco geológico (grau de risco, tipologia, nº de moradias/pessoas afetadas) | `https://geoportal.sgb.gov.br/server/rest/services/gestaoterritorial/risco/FeatureServer/0` (ArcGIS REST, GeoJSON) |
| **INMET** | Chuva horária por estação meteorológica automática | `https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip` (CSV, pacote público anual) |

A CPRM foi renomeada para **SGB**. Os domínios do enunciado original
(`geoportal.cprm.gov.br`, `sace.cprm.gov.br`, `arcgisserver.cprm.gov.br`) ainda
respondem parcialmente, mas a camada de setorização de risco hoje mora em
`geoportal.sgb.gov.br`, sob o certificado TLS de `geoportal.sgb.gov.br`.

## O que mudou em relação ao plano original

O plano inicial previa usar o **CEMADEN** como fonte de chuva. A investigação,
feita com requisições reais e não por suposição, mostrou dois problemas
intransponíveis sem contornar proteções que não pareceu certo contornar:

1. **O download mensal do CEMADEN exige captcha**
   (`mapainterativo.cemaden.gov.br/download/download_form.php`), o que não é
   automatizável de forma honesta.
2. **As únicas camadas do CEMADEN acessíveis sem captcha são espelhos estáticos
   e antigos**: a camada `Cemaden` do próprio geoportal da SGB tem leituras de
   **setembro de 2019**; a camada `precipitacao_bacia_24` do GeoServer oficial
   do CEMADEN (`gsc.cemaden.gov.br`) tem timestamps de **junho de 2017** e é
   agregada por bacia hidrográfica inteira (grão grosseiro demais).

A alternativa avaliada em seguida, a API dinâmica do INMET
(`apitempo.inmet.gov.br/estacao/...`), também não é utilizável por um cliente
não navegador: está atrás de um WAF (cookies `TS...`, padrão de F5 Bot
Defense) que devolve **HTTP 204 vazio** em vez de um erro claro para qualquer
requisição sem uma sessão de navegador legítima.

A solução que sobrou, e que efetivamente funciona sem captcha, sem WAF e sem
navegador automatizado, é o **pacote de dados históricos anuais do INMET**: um
ZIP público por ano com o CSV de cada estação automática do país, atualizado
com poucos dias de defasagem. É o que o ORCA usa hoje. Essa substituição
(CEMADEN → INMET) está documentada também no topo de
[`src/ingest/inmet.py`](src/ingest/inmet.py).

## Arquitetura

```
ORCA/
├── data/                       # dados baixados (gitignored, exceto samples/)
├── docs/
│   └── screenshots/            # imagens usadas neste README
├── scripts/
│   └── atualizar_dados.py      # atalho fino para `python -m src.cli atualizar` (cron/CI)
├── src/
│   ├── cli.py                  # CLI unificada (ingest-cprm, ingest-inmet, atualizar)
│   ├── config.py                # constantes e convenções de caminho compartilhadas
│   ├── storage/
│   │   └── __init__.py         # leitura/gravação de GeoPackage (setores) e CSV (chuva)
│   ├── ingest/
│   │   ├── cprm.py             # cliente ArcGIS REST da CPRM/SGB
│   │   └── inmet.py            # cliente do pacote histórico do INMET
│   ├── processing/
│   │   └── cruzamento.py       # setor → estação mais próxima → chuva 24h/72h
│   └── dashboard/
│       └── app.py              # aplicação Streamlit
├── tests/                      # pytest, com HTTP mockado (sem depender de rede)
└── .github/workflows/
    ├── ci.yml                  # roda a suíte de testes em todo push/PR
    └── atualizar-dados.yml     # atualização diária + publicação como artefato
```

A camada `src/storage/` do plano original chegou a ficar de fora (SQLite/DuckDB
pareciam desnecessários para o volume de dados de um estado). Hoje ela existe
como uma camada fina sobre GeoPackage (setores) e CSV (chuva), usada por
`ingest` e pelo dashboard, sem introduzir dependência de banco.

## Instalação

Requer Python 3.11+.

```bash
git clone <este-repositório>
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

O primeiro download baixa o ZIP anual completo do Brasil (~55MB) e o mantém em
cache local (`data/inmet_<ano>.zip`). Downloads seguintes para outras UFs do
mesmo ano reaproveitam o cache.

### 3. Rodando o dashboard

```bash
streamlit run src/dashboard/app.py
```

Se os dados ainda não existirem localmente, a própria barra lateral tem um
botão **"Baixar/atualizar dados agora"**.

O dashboard mostra o mapa de setores coloridos por grau de risco, um painel
com os setores em atenção (chuva acumulada acima do limiar escolhido) e a
série temporal de chuva por estação. Filtros de UF, município, janela de
acumulado (24h ou 72h) e limiar de atenção ficam todos na barra lateral.

A barra lateral também tem um checkbox **"Verificar novos dados
automaticamente"**: quando ativado, o dashboard passa a checar em segundo
plano, num intervalo configurável de 1 a 30 minutos, se os arquivos locais
foram atualizados por outro processo (o cron diário ou um `orca atualizar`
manual) e recarrega sozinho quando isso acontece. Ele não baixa dados novos
por conta própria, só evita que você precise dar F5 depois de rodar uma
atualização em paralelo.

<p align="center">
  <img src="docs/screenshots/dashboard-atencao.png" alt="Painel de setores em atenção com chuva acima do limiar configurado" width="100%">
</p>

<p align="center">
  <img src="docs/screenshots/dashboard-serie-temporal.png" alt="Gráfico de série temporal de chuva horária de uma estação do INMET" width="100%">
</p>

### 4. Atualização automática

```bash
python scripts/atualizar_dados.py --uf SP --ano 2026
```

Roda as duas ingestões em sequência, tolera a falha de uma fonte sem derrubar
a outra e grava `data/ultima_atualizacao.txt` com o resultado (esse arquivo
também aparece na barra lateral do dashboard). É o mesmo script que o workflow
[`atualizar-dados.yml`](.github/workflows/atualizar-dados.yml) roda todo dia
(cron `0 9 * * *`, mais um `workflow_dispatch` manual), publicando os dados
atualizados como artefato do GitHub Actions.

## Limitações conhecidas

- **A chuva do INMET tem alguns dias de defasagem.** O pacote histórico anual
  não é atualizado minuto a minuto; a "chuva acumulada" mostrada no dashboard
  é sempre relativa à leitura mais recente **disponível**, não necessariamente
  a "agora". O próprio dashboard mostra essa data de referência.
- **Densidade de estações é baixa.** SP tem 40 estações automáticas do INMET
  para 904 setores de risco; a distância média até a estação mais próxima
  fica em torno de 26km (máximo observado: ~74km). Chuva muito localizada
  (comum em eventos convectivos) pode não ser capturada pela estação mais
  próxima de um setor específico.
- **O limiar de atenção (padrão 100mm/72h) é ilustrativo.** É uma referência
  comum na literatura de risco de deslizamento, não um valor oficial calibrado
  para os setores da CPRM/SGB. O próprio dashboard avisa isso e deixa o valor
  livremente ajustável.
- **Cobertura nacional é parcial por design.** O MVP cobre SP; a arquitetura
  já generaliza para qualquer UF (ambos os clientes aceitam `--uf`), mas
  cobrir o Brasil inteiro de uma vez não fazia parte do escopo desta fase.
- **Sem autenticação/multiusuário.** É uma ferramenta local de portfólio, não
  um serviço multiusuário.

## Testes e CI

```bash
pytest
```

22 testes cobrindo: parsing de resposta ArcGIS REST (CPRM/SGB), paginação,
retry com backoff e fallback para cache local; parsing do CSV do INMET
(inclusive valores ausentes), leitura de estação dentro do ZIP anual; a lógica
de cruzamento espacial (estação mais próxima) e temporal (chuva acumulada
24h/72h, incluindo os casos sem dados na janela); e as funções auxiliares do
dashboard (mapeamento de cor por grau de risco, construção do mapa Folium).
Toda chamada de rede é mockada, então a suíte roda sem internet.

O workflow [`ci.yml`](.github/workflows/ci.yml) roda essa suíte a cada push e
a cada pull request, separado do cron diário de atualização de dados.

## Roadmap

- Fallback municipal: camadas próprias de prefeituras em ArcGIS REST, sem
  reescrever o pipeline de ingestão.
- Cobrir mais UFs além de SP.
- Persistir o histórico de chuva incrementalmente (hoje cada ingestão baixa o
  ano inteiro de novo).

## Licença

Projeto de portfólio pessoal. Os dados públicos usados pertencem à CPRM/SGB e
ao INMET; consulte os termos de uso de cada órgão antes de redistribuir.
