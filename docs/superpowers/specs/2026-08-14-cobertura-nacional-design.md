# Cobertura nacional (27 UFs) — design

Data: 2026-08-14

## Contexto

O ORCA cobre hoje só SP: setores de risco da CPRM/SGB cruzados com chuva da
Open-Meteo, exportados para um dashboard estático (`docs/dashboard/`). O
roadmap já listava "cobrir mais UFs" como próximo passo, e a arquitetura de
ingestão já aceita `--uf` em todos os clientes (CPRM, INMET, ANA). O que falta
é generalizar a ingestão/export/dashboard para rodar nas 27 UFs de uma vez,
sem violar o rate limit da Open-Meteo (fonte padrão de chuva do dashboard) e
sem rebaixar o dataset nacional inteiro da CPRM a cada sincronização.

Dois gargalos foram identificados e resolvidos neste design:

1. **CPRM/SGB**: setores mudam pouco — não faz sentido rebaixar o Brasil
   inteiro toda semana só pra achar poucas mudanças.
2. **Open-Meteo**: a chuva por setor precisa ser diária (é o propósito do
   projeto), mas o tier gratuito tem teto de 10.000 chamadas/dia, 5.000/hora,
   600/minuto (confirmado em <https://open-meteo.com/en/pricing>, 14/08/2026).
   Evidência empírica já documentada em `docs/investigacoes.md`: um lote de
   ~900 coordenadas (SP) funciona isolado, mas repetir o volume gera
   `HTTP 429` de forma consistente — indício de que cada coordenada do lote
   pesa perto de 1 "call" no teto. Em escala nacional (~27x o volume de SP),
   uma consulta ingênua de 1 ponto por setor estouraria o teto diário mesmo
   rodando uma vez só por dia.

## Componentes

### 1. Ingestão incremental da CPRM/SGB

Os metadados do FeatureServer (`.../risco/FeatureServer/0?f=json`, checado em
14/08/2026) confirmam que a camada **não expõe controle de edição** nem
**capability de Sync** (`editFieldsInfo: null`,
`capabilities: "Query,Create,Update,Delete,Uploads,Editing"`, sem `Sync` nem
`Extract`). Não há como pedir "só o que mudou desde X" com garantia.

Estratégia adotada — marcador d'água por UF, usando os dois campos
disponíveis que se aproximam de um controle de versão:

- `objectid`: tende a crescer com novos registros.
- `data_setor`: data de levantamento/atualização de campo do setor
  (atributo de domínio, não um campo de sistema).

A cada sincronização, para cada UF, a ingestão consulta apenas
`where=objectid > {last_objectid} OR data_setor > {last_data_setor}` em vez
de baixar a UF inteira, atualiza os registros retornados no GeoPackage local
(merge por `objectid`, preservando os que não voltaram na consulta) e grava
o novo marcador d'água (maior `objectid`/`data_setor` vistos) por UF.

**Limitação aceita e documentada**: uma edição de atributo que não altera
`data_setor` (ex.: corrigir só `num_domi` sem nova visita de campo) não é
capturada por esse filtro, porque a API não expõe nenhum campo que
distinguiria esse caso. Dado que a CPRM atualiza a camada com pouca
frequência, esse é um trade-off aceito — sem revarredura periódica de
reconciliação nesta fase (decisão explícita do usuário).

A ingestão incremental roda com frequência menor que a de chuva (ex.:
semanal), em vez de acoplada ao cron diário de chuva.

### 2. Grade espacial adaptativa para consulta de chuva (Open-Meteo)

Novo componente de processamento que substitui "1 consulta por centróide de
setor" por "1 consulta por célula de grade ocupada", calibrando o tamanho da
célula automaticamente a partir dos dados reais em vez de limiares manuais
por UF/densidade.

- Entrada: centróides de todos os setores de risco nacionais (não por UF
  isolada — UFs vizinhas compartilham células na fronteira).
- Orçamento alvo: uma fração do teto diário da Open-Meteo (ex.: 8.000 de
  10.000 chamadas), deixando margem para a série temporal por município
  (que já usa poucos pontos) e para retries em `HTTP 429`.
- Calibração: busca binária sobre o tamanho de célula (em graus ou metros)
  até o número de células distintas ocupadas convergir para o orçamento
  alvo. Regiões densas (SP, RJ) naturalmente produzem mais células nessa
  resolução (mais detalhe onde há mais setor); regiões esparsas produzem
  poucas células (cada setor isolado vira sua própria célula) — não exige
  limiares de densidade escolhidos à mão.
- Cada setor é associado ao centro da sua célula; setores na mesma célula
  compartilham a mesma leitura de chuva da Open-Meteo.
- O tamanho de célula e o total de células calculado na calibração são
  registrados no metadado da exportação (`meta_<uf>.json` ou um novo
  metadado nacional), para auditoria e ajuste futuro do orçamento alvo.

### 3. Export multi-UF e dashboard

- `exportar_dashboard` continua operando por UF (já é o comportamento
  atual: gera `setores_<uf>.geojson`, `series_<uf>.json`,
  `previsao_<uf>.json`, `meta_<uf>.json`), mas a grade espacial (componente
  2) é calculada uma vez sobre o conjunto nacional antes do loop de export
  por UF, para preservar o compartilhamento de células entre UFs vizinhas.
- Um novo manifesto simples (ex.: `data/ufs_disponiveis.json`) lista as UFs
  com dados exportados, para o front-end popular o seletor.
- `docs/dashboard/index.html`: a constante fixa `const UF = "sp"` vira
  estado de UI com um seletor. Trocar a UF refaz os `fetch` dos arquivos já
  nomeados por UF (nenhuma mudança de formato de arquivo necessária).
- `.github/workflows/atualizar-dados.yml`: o job de atualização passa a
  iterar as 27 UFs numa única execução diária (loop simples, não matrix),
  já que o gargalo de volume de chamadas a Open-Meteo é resolvido pela
  grade compartilhada, não por paralelismo entre UFs.

## Testes

- Ingestão incremental CPRM: teste unitário com fixture simulando resposta
  paginada contendo só registros com `objectid`/`data_setor` acima do
  marcador d'água salvo; verificar merge correto no GeoPackage local e
  atualização do marcador.
- Grade espacial: teste unitário da busca binária com um conjunto sintético
  de centróides (mistura de cluster denso + pontos esparsos) e um orçamento
  alvo pequeno, verificando que o total de células converge dentro do
  orçamento e que setores próximos compartilham célula.
- Export multi-UF: teste de integração leve rodando o export para 2 UFs
  fictícias com poucos setores, verificando que os arquivos por UF são
  gerados e que células de grade são compartilhadas entre elas quando os
  setores estão próximos da fronteira.
- Front-end: verificação manual do seletor trocando UF e conferindo que os
  fetches corretos são disparados (sem framework de teste de front-end no
  projeto hoje).

## Fora de escopo (fica para depois, se necessário)

- Revarredura periódica de reconciliação para pegar edições de atributo
  silenciosas na CPRM (rejeitado nesta fase).
- Fallback municipal (camadas próprias de prefeitura) — investigado à parte
  nesta sessão; sem endpoint público confirmado para o piloto cogitado
  (Itaquaquecetuba), fica pendente de retomada com outro piloto.
- Confirmação por e-mail com a Open-Meteo sobre o peso exato de lotes
  multi-coordenada no rate limit — a calibração por busca binária com
  margem (componente 2) torna essa confirmação não bloqueante.
