# Investigações técnicas do ORCA

Histórico de decisões e investigações técnicas do projeto — fontes
descartadas, motivos, e levantamentos feitos com requisições reais antes de
decidir integrar (ou não) uma fonte de dados. Referenciado a partir do
[README](../README.md#decisões-e-investigações).

## CEMADEN → INMET: por que a fonte de chuva mudou

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
[`src/ingest/inmet.py`](../src/ingest/inmet.py).

## Investigação: fontes de chuva em tempo real

A defasagem do pacote histórico do INMET (dias, não minutos) limita a
utilidade do ORCA num evento de chuva em andamento. Em 07/08/2026 investiguei,
com requisições reais, se havia alguma fonte pública de chuva atualizada
continuamente para substituir ou complementar o INMET.

**ANA (Agência Nacional de Águas), rede telemétrica.** O web service
`https://telemetriaws1.ana.gov.br/ServiceANA.asmx` é público, sem captcha e
sem autenticação. `ListaEstacoesTelemetricas` retorna 5.194 estações em todo
o país (bem mais que as 40 do INMET só em SP), e
`DadosHidrometeorologicos?codEstacao=...&dataInicio=...&dataFim=...` devolve
chuva, nível de rio e vazão em intervalos de 15 minutos. Testado ao vivo: a
estação 58040000 (São Luís do Paraitinga/SP) tinha leitura de poucos minutos
atrás no momento do teste, contra dias de defasagem do INMET.

A ressalva é que a cobertura real é bem menor que a lista sugere. Nem toda
estação listada como "Ativo" transmite dado recente por esse endpoint: de uma
amostra de 25 outras estações de SP (origem RHN, status Ativo), nenhuma tinha
leitura nos últimos dois dias. A rede parece combinar estações com telemetria
de verdade e estações que só reportam manualmente ou em ciclos mais longos, e
não há como distinguir as duas coisas pela lista de estações sozinha. Um
levantamento (varrer os códigos de SP e medir quantos têm dado vivo, e qual a
distância média resultante até os setores de risco) é pré-requisito antes de
integrar essa fonte.

**CEMADEN.** O endpoint de dados recentes das PCDs
(`sws.cemaden.gov.br/PED/rest/pcds/dados_recentes`), mapeado numa investigação
anterior deste projeto, agora retorna 404. Não encontrei substituto
equivalente sem engenharia reversa mais profunda do mapa interativo deles.

Essa investigação está registrada aqui para não se perder; a integração em si
ainda não foi feita (ver [Roadmap](../README.md#roadmap)).

**Atualização (08/08/2026): levantamento de cobertura da ANA em SP.** Rodei
[`scripts/investigar_ana.py`](../scripts/investigar_ana.py), que varre todas as
estações telemétricas da ANA cadastradas em SP e testa, uma a uma, se cada
uma tem leitura de chuva nas últimas 48h (com retry/backoff — o serviço
devolve HTTP 429 com facilidade sob concorrência, e a primeira tentativa sem
isso gerou um falso "quase nada tem dado vivo"). Resultado real: das **437
estações listadas para SP, 271 (62%) têm dado vivo**, com distância mediana
de **18,6km** até o setor de risco mais próximo (média 27,5km, puxada por
alguns outliers a até 190km). Isso é uma cobertura bem mais densa que as 40
estações do INMET em SP (26km de distância média). A ressalva: as estações
com dado vivo são majoritariamente hidrelétricas/fluviométricas (nomes como
"UHE ... BARRAMENTO/JUSANTE"), não uma rede de pluviômetros dedicada — o
campo `Chuva` existe e responde, mas vale checar se a série é
consistente/confiável antes de integrar como fonte de verdade. Com isso, o
pré-requisito do roadmap está atendido e a integração como fonte
complementar ao INMET vale a pena tentar. O design da integração está em
[`docs/superpowers/specs/2026-08-09-ingestao-ana-design.md`](superpowers/specs/2026-08-09-ingestao-ana-design.md).

## Streamlit → dashboard estático

O dashboard nasceu como um app Streamlit (`src/dashboard/app.py`) — a escolha
óbvia pra prototipar rápido um mapa interativo em Python sem escrever
frontend. Funcionalmente resolvia o problema (mapa colorido por grau de
risco, painel de setores em atenção, série temporal por estação, filtros na
barra lateral), mas trouxe três limitações que se acumularam:

1. **Estética genérica.** O chrome padrão do Streamlit (sidebar cinza,
   tipografia e espaçamento fixos) é difícil de customizar visualmente sem
   sair do modelo de componentes do framework.
2. **Layout pouco flexível.** Montar um layout mais deliberado (cards, grids,
   posicionamento fino) dentro do sistema de colunas do Streamlit tem um teto
   baixo.
3. **Sem distribuição como site.** Streamlit precisa de um processo Python
   rodando pra servir a interface — não dá pra publicar como página estática
   (o projeto já tinha uma landing page estática em `docs/index.html` no
   GitHub Pages, mas o dashboard real ficava de fora desse modelo).

A decisão (09/08/2026) foi pré-computar o cruzamento espacial/temporal
(`calcular_cruzamento`, já existente) como arquivos estáticos — GeoJSON dos
setores e JSON da série temporal, recortada aos últimos 30 dias pra não
crescer sem limite agora que o INMET acumula o ano inteiro
(`src/export/dashboard_data.py`, novo) — e servir um dashboard em HTML/CSS/JS
puro (`docs/dashboard/`), sem framework nem build step, reaproveitando só os
tokens de design (cores, tipografia, espaçamento) que já existiam em
`docs/_ds/` a partir da landing page, sem depender do runtime de componentes
dela. Mapa com Leaflet (a mesma engine que o Folium já usava por baixo) e
gráfico com Chart.js, ambos via CDN. Os filtros (município, janela de
acumulado, limiar de atenção) passaram a rodar inteiramente no navegador,
sem round-trip.

Isso trocou o botão "Baixar/atualizar dados agora" (atualização sob demanda)
por um selo de última atualização — sem processo rodando, não há o que
baixar na hora; a atualização passou a vir do cron diário
(`atualizar-dados.yml`), que agora também comita os dados exportados de
volta no repositório pro GitHub Pages publicar. O dashboard Streamlit foi
removido por completo (não manteve como alternativa local), pra não manter
duas UIs divergindo. O design completo está em
[`docs/superpowers/specs/2026-08-09-dashboard-estatico-design.md`](superpowers/specs/2026-08-09-dashboard-estatico-design.md).
