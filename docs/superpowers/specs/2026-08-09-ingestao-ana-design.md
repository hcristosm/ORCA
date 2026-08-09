# Ingestão da ANA como fonte complementar de chuva

Data: 2026-08-09

## Contexto

O README já documenta uma investigação concluída em `scripts/investigar_ana.py`:
das 437 estações telemétricas da ANA cadastradas em SP, 271 (62%) têm dado
vivo de chuva nas últimas 48h, com distância mediana de 18,6km até o setor de
risco mais próximo — cobertura mais densa que as 40 estações do INMET em SP
(26km de distância média). O próximo passo do roadmap é promover essa
investigação a um cliente de ingestão real (`src/ingest/ana.py`) e integrá-lo
ao cruzamento como fonte complementar ao INMET.

## `src/ingest/ana.py`

Segue o mesmo padrão arquitetural de `src/ingest/inmet.py` e
`src/ingest/cprm.py`: uma exceção de domínio (`ANAFetchError`), uma função de
GET com retry/backoff, uma função `fetch_estacoes`, e uma função
`ingerir_uf` que baixa, filtra e persiste.

- **`EstacaoANA`** (dataclass frozen): `codigo, nome, municipio_uf, latitude,
  longitude, status`. Estrutura igual à de `investigar_ana.py`.
- **`fetch_estacoes(uf, timeout, max_retries, backoff_factor, session)`**:
  reaproveita o parsing de `ListaEstacoesTelemetricas` já validado em
  `investigar_ana.py` (filtro por sufixo `-UF` em `Municipio-UF`).
- **`fetch_serie_estacao(codigo, dias_historico, timeout, max_retries,
  backoff_factor, session)`**: generaliza `fetch_ultima_leitura` de
  `investigar_ana.py` para devolver a série completa de `DataHora`/`Chuva` de
  `DadosHidrometeorologicos`, não só o último timestamp. Mesma lógica de
  retry/backoff (o serviço devolve HTTP 429 facilmente sob concorrência —
  documentado e testado em `investigar_ana.py`).
- **Filtro de qualidade**: uma estação só entra no resultado final se tiver ao
  menos uma leitura de chuva não nula nas últimas `janela_horas` (padrão 48h,
  mesma janela da investigação). Documentado no topo do módulo: a maioria das
  estações com dado vivo são hidrelétricas/fluviométricas (nomes como "UHE
  ... BARRAMENTO/JUSANTE"), não pluviômetros dedicados — limitação conhecida
  da rede telemétrica da ANA, não um bug da ingestão.
- **`ingerir_uf(uf, diretorio_dados, dias_historico=4, janela_horas=48,
  max_workers=5, ...)`**:
  1. `fetch_estacoes(uf)`.
  2. Busca a série de cada estação em paralelo (`ThreadPoolExecutor`, como em
     `investigar_ana.py`).
  3. Descarta estações sem leitura recente (filtro de qualidade acima).
  4. Monta um `pd.DataFrame` com o **mesmo schema usado pelo INMET**:
     `data_hora, chuva_mm, codigo_estacao, nome_estacao, uf, latitude,
     longitude`. Isso permite `pd.concat` direto com o DataFrame do INMET sem
     adaptador.
  5. Salva via `storage.salvar_chuva` (CSV) num caminho próprio:
     `data/chuva_ana_<uf>.csv` (nova função `caminho_chuva_ana(uf, data_dir)`
     em `src/config.py`).
  6. Se a busca remota falhar e existir cache local, usa o cache com aviso
     (mesmo padrão de `cprm.ingerir_uf`); se não houver estação alguma com
     dado vivo, levanta `ANAFetchError`.

`dias_historico=4` garante margem suficiente para cobrir a maior janela de
cruzamento (72h) mesmo com alguma degradação de dados perto da borda.

## Cruzamento combinado (`src/processing/cruzamento.py`)

`calcular_cruzamento` ganha um parâmetro opcional `chuva_ana: pd.DataFrame |
None = None`. Quando fornecido:

- Nova função `encontrar_estacao_mais_proxima_combinada(setores, chuva_inmet,
  chuva_ana)`: junta as estações de ambas as fontes num único pool
  geoespacial, cada uma marcada com uma coluna `fonte` (`"inmet"` ou
  `"ana"`), e roda `sjoin_nearest` desse pool contra os setores.
- **Regra de prioridade (explícita e comentada no código):** a distância
  manda — a estação mais próxima do centróide do setor vence, seja ela INMET
  ou ANA. O desempate por recência de leitura só entra em jogo quando duas
  estações de fontes diferentes ficam a uma distância praticamente igual
  (diferença menor que 500m); nesse caso a com leitura mais recente vence. Na
  prática isso quase sempre favorece a ANA (granularidade de 15min) sobre o
  INMET (defasagem de dias) nesses empates.
- O resultado ganha uma coluna `fonte_estacao` (`"inmet"`/`"ana"`) indicando
  qual fonte foi usada para cada setor.
- A função original `encontrar_estacao_mais_proxima` (só INMET) não muda de
  assinatura — continua existindo para quem não passa `chuva_ana`, e
  `calcular_cruzamento` cai nela quando `chuva_ana` é `None` ou vazio,
  preservando compatibilidade com o comportamento atual.

## CLI (`src/cli.py`)

- Novo comando `ingest-ana --uf` (mesmo padrão de `ingest-inmet`/
  `ingest-cprm`, com `--diretorio`, `--janela-horas`, `--max-workers`
  opcionais).
- `atualizar` ganha uma terceira etapa (ANA), com o mesmo padrão try/except
  acumulando em `falhas` — falha isolada na ANA não derruba CPRM/INMET nem
  vice-versa.
- `scripts/atualizar_dados.py` e `.github/workflows/atualizar-dados.yml` não
  precisam de mudança de conteúdo: já são um atalho fino para `python -m
  src.cli atualizar`, que passa a incluir ANA automaticamente.

## Dashboard (`src/dashboard/app.py`)

- Carrega `chuva_ana` (se o CSV existir localmente; sem download automático
  no primeiro carregamento, para não adicionar uma segunda dependência de
  rede obrigatória) e passa para `calcular_cruzamento`.
- Adiciona `fonte_estacao` ao tooltip do mapa Folium e à tabela de "setores
  em atenção", com um rótulo simples (INMET/ANA) — trivial dado que a coluna
  já vem pronta do cruzamento combinado.

## Testes

- `tests/test_ana.py`: parsing do XML/SOAP de `ListaEstacoesTelemetricas` e
  de `DadosHidrometeorologicos` (mockado com `responses`, sem rede); filtro
  de estação sem dado recente; `ingerir_uf` fim a fim mockado (schema de
  saída igual ao do INMET).
- `tests/test_cruzamento.py`: casos novos para o pool combinado — estação ANA
  mais próxima vence quando está mais perto; INMET vence quando está mais
  perto; desempate por recência quando as distâncias empatam; comportamento
  inalterado quando `chuva_ana` é `None` (regressão dos testes existentes).

## README

- Move o item da ANA do Roadmap para a tabela de "Fontes de dados".
- Resume a integração feita na seção "Investigação: fontes de chuva em tempo
  real", sem apagar o histórico da investigação original.
- Atualiza a árvore de arquitetura (`src/ingest/ana.py`) e a contagem/lista
  de testes na seção "Testes e CI".
