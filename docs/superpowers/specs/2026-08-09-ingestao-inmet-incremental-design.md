# Ingestão incremental do INMET

Data: 2026-08-09

## Contexto

`src/ingest/inmet.py` baixa o pacote histórico anual do INMET (ZIP de ~55MB
com um CSV por estação automática do Brasil) e o mantém em cache local em
`data/inmet_<ano>.zip`. Toda execução de `ingest-inmet` baixa e reprocessa o
ano inteiro do zero, mesmo quando só alguns dias novos foram adicionados
desde a última execução — desperdiçando banda e tempo no cron diário
(`atualizar-dados.yml`).

## Investigação: download parcial é possível?

`HEAD` real no ZIP (05/08/2026 → dado ainda válido em 09/08/2026):

```
Accept-Ranges: bytes
ETag: "3494b0e-6584aef188760"
Content-Length: 55134990
```

O servidor suporta `Range` e `ETag`/requisição condicional, mas **dentro do
ZIP cada estação tem um único arquivo cobrindo o ano inteiro** — não há
granularidade por dia ou mês no lado do servidor. Mesmo usando `Range` para
extrair só a entrada de uma estação, ainda viria o ano inteiro dela. **Não
existe forma de baixar só o delta por data do servidor.** As duas otimizações
honestas disponíveis:

1. Pular o download inteiro quando o ZIP não mudou desde a última execução
   (`If-None-Match` com o `ETag` salvo → `304 Not Modified`).
2. Reprocessar localmente só o que mudou, por estação, usando o CRC32 de cada
   entrada do ZIP (metadado disponível sem descompactar) comparado ao CRC32
   registrado na última execução.

Essa limitação (sem download parcial por data) é documentada no topo do
módulo, junto com a explicação de por que a otimização é local.

## Rastreamento de estado

Manifesto JSON por UF/ano: `data/inmet_manifest_<uf>_<ano>.json`
(`caminho_manifesto_inmet(uf, ano, data_dir)` em `src/config.py`):

```json
{
  "etag_zip": "\"3494b0e-6584aef188760\"",
  "estacoes": {
    "A701": {"crc32": 123456789, "ultima_data_hora": "2026-08-05T23:00:00Z"}
  }
}
```

Preferido a reaproveitar `ultima_atualizacao.txt` (texto solto, sem
granularidade por estação, usado pela CLI para outro propósito — CPRM/INMET
juntos) ou a inferir tudo do CSV de saída (não guarda CRC do ZIP, então não
permitiria pular estações sem reabrir e reparsear o CSV, perdendo a principal
otimização). Um arquivo dedicado e pequeno, só para esse propósito, é o mais
simples de manter sem acoplar a outro arquivo com responsabilidade diferente.

## Fluxo de `ingerir_uf`

1. Baixa o ZIP com `If-None-Match: <etag salvo>`; em `304`, reaproveita o ZIP
   em cache sem nova transferência. Em `200`, salva o novo ZIP e ETag.
2. Para cada estação do UF:
   - Lê o CRC32 da entrada no ZIP (via `zipfile.ZipInfo`, sem descompactar).
   - Se igual ao CRC32 do manifesto: **pula** — reaproveita as linhas já
     salvas no CSV acumulado para essa estação, sem reparsear.
   - Se diferente (ou estação nova, ou primeira execução): parseia o CSV da
     estação normalmente (`_parse_csv_estacao`, sem mudança), mas só
     **mescla** no CSV acumulado as linhas com
     `data_hora >= última_data_hora_salva − 7 dias` (janela de retificação).
     Linhas mais antigas do CSV acumulado ficam intocadas.
   - Dentro da janela mesclada, dedupe por `(codigo_estacao, data_hora)`
     priorizando o valor recém-baixado — trata retificação do INMET (mesmo
     timestamp, `chuva_mm` diferente). Fora da janela, assume-se que os dados
     já são estáveis (limitação documentada: não há SLA oficial do INMET
     sobre até quando uma leitura pode ser corrigida; 7 dias é uma escolha
     conservadora, não uma garantia).
3. Escreve o CSV acumulado (merge, não overwrite do zero) e atualiza o
   manifesto (CRC32 e última `data_hora` por estação, novo ETag do ZIP).

Assinatura pública de `ingerir_uf(uf, ano, diretorio_dados, ...)` não muda —
quem chama (`src.cli ingest-inmet --uf SP --ano 2026`) não percebe diferença
de interface, só de desempenho a partir da segunda execução.

## Testes

`tests/test_inmet.py` ganha:

- Primeira execução (sem manifesto): processa e salva todas as estações
  normalmente — regressão do comportamento atual.
- Segunda execução com um ZIP onde uma estação tem CRC igual (deve ser
  pulada, sem reparsear) e outra tem CRC diferente com linhas novas (deve
  mesclar, preservando linhas antigas fora da janela de 7 dias).
- Caso de retificação: mesma `data_hora` dentro da janela de 7 dias com
  `chuva_mm` diferente entre a execução antiga e a nova — o valor novo deve
  prevalecer no CSV final.

## README

- Remove "Persistir o histórico de chuva incrementalmente" do Roadmap.
- Atualiza "Limitações conhecidas": explica que o INMET só oferece o ZIP
  anual completo (sem range por data no servidor), que a otimização é local
  via CRC por estação + manifesto, e que retificações só são capturadas
  dentro da janela de 7 dias.
