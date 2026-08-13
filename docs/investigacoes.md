# Investigações técnicas do ORCA

Registro velho de escolha e busca técnica do projeto: fonte descartada, motivo por trás, e teste feito com requisição real antes de decidir usar (ou não) fonte de dado. Ver [README](../README.md#decisões-e-investigações).

## CEMADEN → INMET: por que fonte de chuva mudou

Plano primeiro queria **CEMADEN** pra chuva. Teste real, não chute, achou dois problema sem jeito de contornar sem burlar proteção, e burlar não pareceu certo:

1. **Download mensal do CEMADEN pede captcha**
   (`mapainterativo.cemaden.gov.br/download/download_form.php`), não dá pra automatizar honesto.
2. **Única camada CEMADEN sem captcha é espelho velho parado**: camada `Cemaden` do geoportal SGB tem leitura de **setembro 2019**; camada `precipitacao_bacia_24` do GeoServer oficial CEMADEN (`gsc.cemaden.gov.br`) tem timestamp de **junho 2017** e junta por bacia inteira (grão grosso demais).

Alternativa testada depois, API dinâmica do INMET (`apitempo.inmet.gov.br/estacao/...`), também não presta pra cliente sem navegador: atrás de WAF (cookie `TS...`, padrão F5 Bot Defense) que devolve **HTTP 204 vazio** em vez de erro claro pra quem não tem sessão de navegador de verdade.

Solução que sobrou, e que funciona sem captcha, sem WAF, sem navegador robô, é o **pacote histórico anual do INMET**: ZIP público por ano com CSV de cada estação automática do país, atrasa só poucos dias. ORCA usa isso hoje. Troca (CEMADEN → INMET) documentada também no topo de [`src/ingest/inmet.py`](../src/ingest/inmet.py).

## Investigação: fonte de chuva em tempo real

Atraso do pacote histórico INMET (dias, não minuto) limita ORCA num evento de chuva rolando agora. Em 07/08/2026 testei, com requisição real, se tem fonte pública de chuva atualizada sem parar pra trocar ou somar com INMET.

**ANA (Agência Nacional de Águas), rede telemétrica.** Web service `https://telemetriaws1.ana.gov.br/ServiceANA.asmx` é público, sem captcha, sem login. `ListaEstacoesTelemetricas` devolve 5.194 estação no país inteiro (bem mais que as 40 do INMET só em SP), e `DadosHidrometeorologicos?codEstacao=...&dataInicio=...&dataFim=...` dá chuva, nível de rio e vazão a cada 15 minuto. Testado ao vivo: estação 58040000 (São Luís do Paraitinga/SP) tinha leitura de poucos minuto atrás na hora do teste, contra dias de atraso do INMET.

Ressalva: cobertura real bem menor que lista sugere. Nem toda estação marcada "Ativo" manda dado recente por esse endpoint: de amostra de 25 outra estação de SP (origem RHN, status Ativo), nenhuma tinha leitura nos último dois dia. Rede parece misturar estação com telemetria de verdade e estação que só manda manual ou em ciclo longo, sem jeito de distinguir só pela lista. Levantamento (varrer código de SP, medir quanto tem dado vivo, e distância média até setor de risco) é pré-requisito antes de integrar essa fonte.

**CEMADEN.** Endpoint de dado recente das PCDs (`sws.cemaden.gov.br/PED/rest/pcds/dados_recentes`), mapeado em investigação anterior deste projeto, agora devolve 404. Não achei substituto equivalente sem engenharia reversa mais funda do mapa interativo deles.

Investigação anotada aqui pra não perder; integração em si ainda não feita (ver [Roadmap](../README.md#roadmap)).

**Atualização (08/08/2026): levantamento de cobertura da ANA em SP.** Rodei [`scripts/investigar_ana.py`](../scripts/investigar_ana.py), que varre toda estação telemétrica ANA cadastrada em SP e testa, uma por uma, se tem leitura de chuva nas últimas 48h (com retry/backoff: serviço devolve HTTP 429 fácil sob concorrência, primeira tentativa sem isso deu falso "quase nada tem dado vivo"). Resultado real: das **437 estação listada pra SP, 271 (62%) têm dado vivo**, distância mediana de **18,6km** até setor de risco mais próximo (média 27,5km, puxada por outlier até 190km). Cobertura bem mais densa que as 40 estação do INMET em SP (26km distância média). Ressalva: estação com dado vivo é majoritariamente hidrelétrica/fluviométrica (nome tipo "UHE ... BARRAMENTO/JUSANTE"), não rede de pluviômetro dedicada; campo `Chuva` existe e responde, mas vale checar se série é consistente antes de usar como fonte de verdade. Com isso, pré-requisito do roadmap atendido, integração como fonte extra do INMET vale tentar.

## Streamlit → dashboard estático

Dashboard nasceu como app Streamlit (`src/dashboard/app.py`), escolha óbvia pra prototipar rápido mapa interativo em Python sem escrever frontend. Resolvia o problema (mapa colorido por grau de risco, painel de setor em atenção, série temporal por estação, filtro na barra lateral), mas trouxe três limite que foram se acumulando:

1. **Estética genérica.** Chrome padrão do Streamlit (sidebar cinza, tipografia e espaçamento fixo) difícil de customizar sem sair do modelo de componente do framework.
2. **Layout pouco flexível.** Montar layout mais caprichado (card, grid, posicionamento fino) dentro do sistema de coluna do Streamlit tem teto baixo.
3. **Sem distribuição como site.** Streamlit precisa de processo Python rodando pra servir a interface; não dá pra publicar como página estática (projeto já tinha landing page estática em `docs/index.html` no GitHub Pages, mas dashboard real ficava de fora desse modelo).

Decisão (09/08/2026) foi pré-computar o cruzamento espacial/temporal (`calcular_cruzamento`, já existia) como arquivo estático: GeoJSON dos setores e JSON da série temporal, recortada aos último 30 dias pra não crescer sem limite agora que INMET acumula ano inteiro (`src/export/dashboard_data.py`, novo), e servir dashboard em HTML/CSS/JS puro (`docs/dashboard/`), sem framework nem build step, reaproveitando só token de design (cor, tipografia, espaçamento) que já existia em `docs/_ds/` vindo da landing page, sem depender do runtime de componente dela. Mapa com Leaflet (mesma engine que Folium já usava por baixo) e gráfico com Chart.js, ambos via CDN. Filtro (município, janela de acumulado, limiar de atenção) passou a rodar tudo no navegador, sem round-trip.

Isso trocou botão "Baixar/atualizar dados agora" (atualização sob pedido) por selo de última atualização, já que sem processo rodando não tem o que baixar na hora; atualização passou a vir do cron diário (`atualizar-dados.yml`), que agora também comita dado exportado de volta no repositório pro GitHub Pages publicar. Dashboard Streamlit foi removido de vez (não guardou como alternativa local), pra não manter duas UI divergindo.

## Open-Meteo como fonte padrão do dashboard

INMET tem uns dia de atraso (ver primeira seção deste documento). Em 10/08/2026 testei a [Open-Meteo](https://open-meteo.com/) (`https://api.open-meteo.com/v1/forecast`) como alternativa: diferente do INMET (ZIP anual por estação) e da ANA (rede telemétrica com estação), Open-Meteo dá chuva horária **por coordenada**: sem conceito de estação, dá pra consultar direto o centro de cada setor de risco, sem precisar de "estação mais perto".

**Achado com requisição real:**

- `GET` com muita coordenada na query string bate em `HTTP 414 URI Too
  Long` bem antes de chegar a algumas centena de ponto. `POST` com `latitude`/`longitude` como array no corpo é obrigatório pra lote grande.
- Parâmetro `timezone` não pode ir como string simples nesse modo (API pede array, um valor por coordenada); deixar de fora faz API responder em GMT, equivale a UTC pros fim deste projeto.
- Um `POST` só com as ~900 coordenada dos 904 setor de SP respondeu em ~2s numa primeira tentativa isolada, mas repetir esse volume de requisição (como aconteceu naturalmente durante desenvolvimento e teste desta integração) ou pedir muito dia de histórico de uma vez pra todo setor gera `HTTP 429 Minutely API request limit
  exceeded` de jeito consistente. Limite prático parece depender do volume (coordenada × dia pedido), não só da frequência de chamada: às vez esperar o minuto que a própria API pede não basta se cota do período (hora/dia) já foi gasta por teste anterior.

**Decisão de integração:** `src/ingest/openmeteo.py` (novo) divide consulta em lote de 50 coordenada com pequena pausa entre lote, e trata `HTTP 429` com espera fixa de 60s (em vez do backoff exponencial curto usado pra outro erro transitório). `src/export/dashboard_data.py` usa janela de histórico menor (4 dias, só o necessário pro acumulado de 72h) na consulta por setor (que é a maior, com ~900 ponto) e mantém 30 dias só na consulta por município (bem menor, ~100 ponto) que alimenta o gráfico de série temporal. Virou fonte padrão da exportação do dashboard (`exportar_dashboard(..., fonte="openmeteo")`), sem tirar o caminho por estação (INMET/ANA) que já existia; `--fonte inmet` continua disponível.