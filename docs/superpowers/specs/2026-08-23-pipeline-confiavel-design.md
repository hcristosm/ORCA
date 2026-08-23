# Pipeline confiável: isolar fontes externas e tornar a publicação reversível

Data: 2026-08-23
Status: aprovado, aguardando plano de implementação

## 1. O incidente

O run #29 do workflow `atualizar-dados.yml` (2026-08-23 09:22 UTC, commit
`b9be0f9`) publicou um dashboard com **2 das 27 UFs** e encerrou com
**todos os passos em `success`**.

O `gh-pages` foi reescrito com apenas AP e BA, apagando as 25 UFs que
estavam publicadas e funcionando. Como o deploy usa `force_orphan: true`,
a branch tem exatamente um commit: **as UFs destruídas não eram
recuperáveis pelo git**.

## 2. Diagnóstico

Confirmado no log bruto do run (`gh run view 32630825599 --log`).

### 2.1 Causa imediata

25 UFs falharam na ingestão CPRM/SGB, todas com o mesmo erro:

```
HTTPSConnectionPool(host='geoportal.sgb.gov.br', port=443):
Read timed out. (read timeout=30.0)
```

As três tentativas (backoff 1s/2s/4s) esgotaram para cada UF. As UFs que
sobreviveram — AP e BA — são alfabeticamente consecutivas, compatível com
uma janela curta de disponibilidade do serviço.

### 2.2 Por que o job ficou verde

Três decisões independentes se somaram:

1. `data/*` está no `.gitignore`, então o CI **sempre** parte do zero e
   refaz toda a ingestão CPRM a cada execução. A ingestão incremental com
   marcador d'água (`_where_incremental`) não tem efeito nenhum no CI.
2. Falha de CPRM não é fatal: `src/cli.py` apenas registra em stderr, e
   `src/export/nacional.py` pula UFs sem setores locais com um warning.
3. O código de saída exige **uma única** UF:
   `if not resultados: raise typer.Exit(code=1)`. 2 de 27 satisfaz.

### 2.3 Falhas secundárias reveladas pelo log

**Vento:** falhou nas duas UFs sobreviventes, por timeout contra
`servicodados.ibge.gov.br/api/v3/malhas/estados/<UF>`. Verificado em
2026-08-23 a partir do Brasil: o IBGE responde em 0,096s com HTTP 200 —
o serviço está saudável. **A falha foi do runner alcançando `.gov.br`,
não do IBGE.**

Dois `.gov.br` independentes falharam por timeout no mesmo run enquanto a
Open-Meteo (europeia) respondeu normalmente. Timeout de 30s com sete
segundos de backoff total é curto para endpoints brasileiros alcançados
da rede do GitHub.

**Triagem por chuva prevista:** o log adicionado em `acc7315` registrou
`0 de 8` (AP) e `0 de 93` (BA) municípios com série completa.

Investigado: **não é bug.** O `previsao` é construído iterando o mesmo
`setores["num_setor"]` que a triagem depois consulta, então não há key
mismatch — a hipótese registrada no commit não se concretizou. O zero vem
do limiar: `LIMIAR_ATENCAO_MM_PADRAO = 100.0` exige 100mm em 72h, um evento
severo. Zero na Bahia em agosto é o resultado correto.

Isso expõe um problema de desenho — o limiar de *alerta* foi reaproveitado
como limiar de *triagem de histórico*, e na prática o grupo de 30 dias fica
permanentemente vazio. **Fora do escopo deste documento** (ver §9).

## 3. Princípios

1. **Isolar fontes externas por cadência.** Dado quase estático não deve
   ser rebaixado diariamente de um serviço instável.
2. **Nenhuma publicação destrói dado bom.** Degradar é envelhecer, nunca
   desaparecer.
3. **Todo estrago é reversível.** Rollback por construção, não por sorte.
4. **Verificar o site, não só o build.** Todos os passos do run #29
   passaram.

## 4. Escopo

### 4.1 Remover a camada de vento

Remove `src/export/vento_data.py`, `src/ingest/ibge.py`,
`src/processing/vento.py`, `centroides_ibge` de
`src/processing/cruzamento.py`, `fetch_vento_batch` de
`src/ingest/openmeteo.py`, a chamada `exportar_vento` em `src/cli.py`, a
camada no `docs/dashboard/index.html`, os testes `test_export_vento.py`,
`test_ibge.py`, `test_vento.py` e o teste de `centroides_ibge` em
`test_cruzamento.py`.

Remove também os 9 `docs/dashboard/data/vento_*.geojson` versionados em
`main`, resíduos de execuções antigas.

Verificado: o IBGE é usado **exclusivamente** pelo vento. `centroides_ibge`
tem um único chamador (`vento_data.py`), e `src/ingest/ibge.py` só é
importado por ele. **Remover o vento elimina uma das duas dependências
`.gov.br` por inteiro.**

### 4.2 Separar a ingestão CPRM em workflow mensal

Novo `.github/workflows/ingerir-setores.yml`, `cron: "0 6 1 * *"` mais
`workflow_dispatch`. Roda só a ingestão CPRM das 27 UFs e publica os
GeoPackages na branch órfã `dados-base`.

`atualizar-dados.yml` deixa de tocar na SGB: baixa os setores do
`dados-base` e roda apenas a exportação Open-Meteo.

Exige extrair a ingestão CPRM de `atualizar-nacional` em `src/cli.py` para
um comando próprio, de modo que os dois workflows invoquem coisas distintas.

Com a ingestão mensal, os timeouts da CPRM passam a ser generosos (sem
pressa num job mensal): timeout maior e mais tentativas com backoff mais
longo.

### 4.3 Recuperar as 27 UFs

O artefato `dados-orca-nacional` do run #28 (id `32611495610`, 17,3MB,
2026-08-23 03:52) contém o conjunto completo. Retenção de 14 dias.

Semear o `dados-base` a partir dele restaura as 27 UFs **sem depender da
SGB voltar**. Passo urgente e independente do resto.

### 4.4 Reorganizar o armazenamento

Estado final, uma branch por ciclo de vida:

| Branch | Conteúdo | Escrito por | Histórico |
|---|---|---|---|
| `dados-base` | GeoPackages de setores + manifestos | mensal | sim |
| `cache-openmeteo` | `openmeteo.sqlite` (~45MB) | diário | não (`force_orphan`) |
| `gh-pages` | dashboard estático + JSONs (poucos MB) | diário | **sim** |

Tirar o cache do `gh-pages` permite **abandonar o `force_orphan`** e manter
histórico. Qualquer publicação ruim passa a estar a um `git revert` de
distância. Era o `force_orphan` que tornava o incidente irreversível, e ele
existia só por causa do blob de 45MB mudando diariamente.

### 4.5 Publicação não-destrutiva

Antes de publicar, o job diário busca o `gh-pages` atual e preserva os
`data/*.json` e `*.geojson` das UFs que este run não regenerou. UF que
falhou continua no dashboard com o dado anterior.

### 4.6 Selo de defasagem

`docs/dashboard/index.html` já exibe `referencia` e `gerado_em`. Acrescentar
realce explícito quando `gerado_em` for mais velho que um ciclo diário, para
que a defasagem seja lida em vez de interpretada.

### 4.7 Alarme de cobertura

- **Mensal (CPRM):** falha se **qualquer** UF falhar após os retries. É
  mensal, então a notificação é rara e sempre significativa; ignorar custa
  uma UF congelada por um mês.
- **Diário (Open-Meteo):** falha abaixo de **90%** de cobertura, ajustável
  por variável do workflow.

Nos dois casos a publicação mantém `if: always()`: falhar o job nunca
impede a mescla de ir ao ar.

### 4.8 Teste de fumaça no site publicado

Passo final do job diário: busca a URL pública e afirma invariantes —
`ufs_disponiveis.json` traz pelo menos o mesmo piso de §4.7 (90% das UFs
esperadas), cada `meta_<uf>.json` faz
parse, `referencia` não é absurdamente antiga.

Justificativa: toda verificação anterior valida o build, e o build do run
#29 foi integralmente bem-sucedido. Este passo cobre classes de falha ainda
não imaginadas — **incluindo bugs no próprio passo de mescla**, que passa a
ser a rede de segurança do sistema e, por isso, seu ponto único mais
perigoso.

### 4.9 Sanidade antes de publicar

Afirmar invariantes no dado gerado antes do deploy: `total_setores > 0`,
geojson faz parse, série não vazia. Impede que dado corrompido seja
publicado, enquanto §4.8 detecta depois do fato.

## 5. Testes

Testáveis sem rede, via pytest:

- **Mescla:** UF ausente no run preserva a anterior; UF presente sobrescreve;
  run vazio preserva tudo.
- **Cobertura:** cálculo contra o piso, incluindo as bordas (exatamente no
  piso, zero UFs, todas as UFs).
- **Sanidade:** rejeita `total_setores == 0` e geojson malformado.

A separação dos workflows verifica-se por `workflow_dispatch` manual.

## 6. Riscos

- **A mescla vira ponto único de falha.** Mitigado por §4.8 e por testes
  dedicados.
- **A recuperação depende de um artefato que expira.** Executar §4.3 antes
  de 2026-09-06.
- **A SGB pode continuar fora quando o mensal rodar.** Aceitável: os setores
  do `dados-base` permanecem válidos e o dashboard não é afetado.

## 7. Fora de escopo

- **Limiar da triagem por chuva** (§2.3). Decisão de domínio, não de
  engenharia. Misturá-la a uma correção de infraestrutura destruiria a
  capacidade de atribuir causa a efeito.
- `scripts/investigar_ana.py`, grade espacial, rate limiter, schema do cache.
- Ingestão INMET/ANA.

## 8. Nota de ambiente

`pytest` não está instalado no ambiente local de desenvolvimento: os testes
não podem ser rodados fora do CI hoje. Rodar `pip install -e ".[dev]"`.
