# Reestruturação visual do README

Data: 2026-08-09

## Contexto

O `README.md` atual (312 linhas) documenta o projeto de forma completa e
honesta — inclusive investigações técnicas detalhadas (troca CEMADEN→INMET,
levantamento de cobertura da ANA) — mas isso o deixa denso: seções de texto
corrido longas competem por atenção com o essencial (o que o projeto faz,
como instalar, como rodar). O pedido é reestruturar e enxugar, sem perder
rastreabilidade do conteúdo técnico já documentado.

## Decisões (confirmadas com o usuário)

1. **Enxugar, não só reorganizar.** Conteúdo é condensado, não só
   redistribuído.
2. **Conteúdo histórico/investigativo move para `docs/investigacoes.md`**,
   preservado verbatim (datas, números, rastreabilidade), com um resumo
   curto + link no README.
3. **Árvore de pastas ASCII vira diagrama Mermaid** de fluxo de dados no
   corpo do README (a árvore de pastas detalhada não fica mais no corpo
   principal).

## Estrutura nova do README

1. **Header** — badges e imagem de topo, sem mudança.
2. **Sobre** — narrativa pessoal (geólogo, PMRR de Itaquaquecetuba, visão
   computacional), sem cortes de conteúdo.
3. **Sumário** — âncoras atualizadas para a nova estrutura.
4. **Fontes de dados** — tabela CPRM/SGB + INMET, sem mudança de conteúdo.
   ANA e ingestão incremental do INMET **não entram** nessa tabela: ainda
   não estão implementadas no código (só têm spec em
   `docs/superpowers/specs/`), e a tabela reflete o que o projeto
   efetivamente faz hoje.
5. **Arquitetura** — diagrama Mermaid (`flowchart`) mostrando o fluxo:
   CPRM/SGB e INMET → `src/ingest/` → `src/storage/` → `src/processing/` →
   `src/dashboard/`. Substitui a árvore ASCII de pastas do README atual.
6. **Instalação** — sem mudança de conteúdo, frases revisadas para parágrafos
   mais curtos onde fizer sentido.
7. **Uso** (1–4: CPRM, INMET, dashboard, atualização automática) — sem corte
   de conteúdo técnico (comandos, exemplos, caminhos de saída), só
   condensação de frases longas.
8. **Limitações conhecidas** — mantida como lista, sem cortes.
9. **Testes e CI** — mantida, condensada.
10. **Decisões e investigações** *(nova seção, substitui "O que mudou em
    relação ao plano original" e "Investigação: fontes de chuva em tempo
    real")* — dois resumos de 3–4 linhas:
    - CEMADEN → INMET: por que o CEMADEN foi descartado (captcha, camadas
      estáticas antigas) e por que o pacote anual do INMET foi a solução
      viável.
    - Investigação da ANA: achado principal (271/437 estações com dado vivo
      em SP, distância mediana 18,6km) e a ressalva (estações
      majoritariamente hidrelétricas/fluviométricas).
    Cada resumo termina com "detalhes completos → `docs/investigacoes.md`".
11. **Roadmap** e **Licença** — sem mudança de conteúdo.

## `docs/investigacoes.md` (novo arquivo)

Recebe o conteúdo integral e verbatim das duas seções removidas do README:
"O que mudou em relação ao plano original" e "Investigação: fontes de chuva
em tempo real" (incluindo a atualização de 08/08/2026 sobre a ANA). Só muda
de arquivo — nenhuma data, número ou trecho é reescrito ou resumido aqui.
Recebe um título e uma linha de contexto no topo explicando que é o histórico
de decisões técnicas do projeto, referenciado a partir do README.

## Fora de escopo

- Não atualiza conteúdo técnico para refletir as specs de ANA/INMET
  incremental já escritas (`docs/superpowers/specs/2026-08-09-*`) — essas
  specs ainda não viraram código, então o README continua descrevendo o
  estado atual do projeto, não o planejado.
- Não altera `docs/screenshots/` nem a lógica de nenhum módulo em `src/`.
