/* Funções usadas pelos três scripts do dashboard (index.html, relatorio.js e
   areas-customizadas.js), que antes mantinham cópias idênticas de cada uma.
   Carregado antes dos outros dois; expõe `window.ORCA`. */
(function () {
  "use strict";

  /* Escapa texto para interpolação em template de HTML. Usa a serialização
     do próprio DOM (textContent -> innerHTML) em vez de uma tabela de
     substituições à mão: o navegador já sabe o que precisa virar entidade. */
  function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto == null ? "" : String(texto);
    return div.innerHTML;
  }

  /* Lê uma custom property do CSS (ex.: "--risco-alto"). O tema vive todo no
     CSS, então a cor sai de lá e não de uma cópia em JS que sairia de sincronia. */
  function token(nome) {
    return getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
  }

  /* Timeout explícito em toda busca de terceiro. Host que *pendura* não rejeita
     o `fetch`: sem isto a promessa nunca assenta, e quem espera por ela trava
     em silêncio (foi o que sumiu com a camada de raios). */
  const TIMEOUT_PADRAO_MS = 8000;

  async function fetchComTimeout(url, ms = TIMEOUT_PADRAO_MS) {
    const controlador = new AbortController();
    const idTimeout = setTimeout(() => controlador.abort(), ms);
    try {
      return await fetch(url, { signal: controlador.signal });
    } finally {
      clearTimeout(idTimeout);
    }
  }

  const FORECAST_URL = "https://api.open-meteo.com/v1/forecast";
  const DIAS_HISTORICO_PADRAO = 4;
  const DIAS_PREVISAO_PADRAO = 4;

  /* Chuva horária de UM ponto, direto da Open-Meteo. Um ponto custa quase nada
     de quota, ao contrário da UF inteira (SP são ~900 pontos de grade), então o
     navegador pode fazer isto sob demanda. Usada pela aba "Minhas áreas" e pelo
     "Atualizar agora" do município. */
  async function buscarChuvaOpenMeteo(lat, lon, opcoes = {}) {
    const url = new URL(FORECAST_URL);
    url.searchParams.set("latitude", lat);
    url.searchParams.set("longitude", lon);
    url.searchParams.set("hourly", "precipitation");
    url.searchParams.set("past_days", String(opcoes.diasHistorico || DIAS_HISTORICO_PADRAO));
    url.searchParams.set("forecast_days", String(opcoes.diasPrevisao || DIAS_PREVISAO_PADRAO));

    const resp = await fetchComTimeout(url, opcoes.timeoutMs);
    if (!resp.ok) {
      throw new Error(`Open-Meteo respondeu ${resp.status}. Tente novamente em instantes.`);
    }
    const dados = await resp.json();
    const horario = (dados && dados.hourly) || {};
    const horas = horario.time || [];
    const precipitacoes = horario.precipitation || [];
    return horas.map((iso, i) => ({
      dataHoraMs: Date.parse(iso.endsWith("Z") ? iso : `${iso}Z`),
      chuvaMm: typeof precipitacoes[i] === "number" ? precipitacoes[i] : null,
    }));
  }

  /* Soma a chuva da série na janela que termina em `referenciaMs`. Devolve
     `null` quando a janela não tem nenhum valor: zero medido e ausência de
     medida não são a mesma coisa. */
  function chuvaAcumulada(serie, referenciaMs, horas) {
    const inicio = referenciaMs - horas * 3600 * 1000;
    let soma = 0;
    let temValor = false;
    for (const ponto of serie) {
      if (ponto.dataHoraMs > inicio && ponto.dataHoraMs <= referenciaMs && typeof ponto.chuvaMm === "number") {
        soma += ponto.chuvaMm;
        temValor = true;
      }
    }
    return temValor ? soma : null;
  }

  /* Última hora JÁ OBSERVADA da série. A Open-Meteo devolve observação e
     previsão na mesma lista, e acumular até "agora" misturaria as duas. */
  function referenciaObservada(serie, agoraMs) {
    const validos = serie.filter(p => p.dataHoraMs <= agoraMs && typeof p.chuvaMm === "number");
    if (!validos.length) return agoraMs;
    return Math.max(...validos.map(p => p.dataHoraMs));
  }

  window.ORCA = Object.assign(window.ORCA || {}, {
    escaparHtml, token, fetchComTimeout,
    buscarChuvaOpenMeteo, chuvaAcumulada, referenciaObservada,
  });
})();
