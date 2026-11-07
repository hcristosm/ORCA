/* Tela "Perto de mim" (celular): veredito de risco para o ponto onde se está
   e os setores oficiais da CPRM mais próximos.

   Tudo no aparelho: GPS do navegador, índice estático de setores
   (data/setores_pontos.json) e UMA chamada à Open-Meteo com o ponto e os
   setores. O cálculo está em calculo.js (sem DOM); aqui só se busca, guarda e
   desenha.

   Cada falha tem texto próprio. "Sem dado" nunca aparece como "Sem alerta". */
(function () {
  "use strict";

  const { escaparHtml, fetchComTimeout, buscarChuvaVariosPontos, chuvaAcumulada, referenciaObservada } = window.ORCA;
  const calc = () => window.ORCA.calculo;

  const CHAVE_ULTIMO = "orca-perto-ultimo";
  const RECONSULTAR_APOS_MS = 10 * 60 * 1000;
  const URL_INDICE = "data/setores_pontos.json";

  let indice = null;           // setores lidos do índice (lerIndice)
  let referenciaPorUf = {};
  let erroIndice = false;

  let ponto = null;            // { lat, lon, rotulo, origem: "gps" | "municipio", precisaoM }
  let estadoGps = "nunca";     // "nunca" | "pedindo" | "ok" | "negado"
  let proximos = [];           // saída de setoresProximos
  let seriePonto = null;       // série horária do ponto, ou null
  let seriesSetores = [];      // uma por próximo, ou null
  let consultadoEm = 0;
  let consultando = false;

  /* ------------------------------------------------------------ utilitários */

  function horaBrasilia(ms) {
    return new Date(ms).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", timeStyle: "short" });
  }

  function dataHoraBrasilia(ms) {
    return new Date(ms).toLocaleString("pt-BR", { timeZone: "America/Sao_Paulo", dateStyle: "short", timeStyle: "short" });
  }

  function mm(v) {
    return typeof v === "number" ? `${v.toFixed(1).replace(".", ",")} mm` : "—";
  }

  function formatarDistancia(km) {
    return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1).replace(".", ",")} km`;
  }

  function rotuloGrau(grau) {
    return grau ? grau.charAt(0).toUpperCase() + grau.slice(1) : "—";
  }

  function criterio() {
    return window.ORCA_painel?.criterio?.() || { janela: 72, limiar: 100 };
  }

  function el(id) { return document.getElementById(id); }

  function aviso(texto) {
    const p = el("pertoAviso");
    p.textContent = texto || "";
    p.hidden = !texto;
  }

  /* ------------------------------------------------------------ busca */

  async function carregarIndice() {
    if (indice) return;
    try {
      const resp = await fetchComTimeout(URL_INDICE);
      if (!resp.ok) throw new Error(`HTTP ${resp.status} em ${URL_INDICE}`);
      const json = await resp.json();
      indice = calc().lerIndice(json);
      referenciaPorUf = json.referencia_por_uf || {};
      erroIndice = false;
    } catch (e) {
      console.warn("Índice de setores indisponível:", e);
      indice = null;
      erroIndice = true;
    }
  }

  function obterPosicao() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) { reject(new Error("sem geolocalização")); return; }
      navigator.geolocation.getCurrentPosition(resolve, reject,
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    });
  }

  async function permissaoGps() {
    try {
      const status = await navigator.permissions.query({ name: "geolocation" });
      return status.state;
    } catch (e) {
      return "prompt";
    }
  }

  async function localizar() {
    estadoGps = "pedindo";
    desenharVeredito({ carregando: "Localizando…" });
    try {
      const pos = await obterPosicao();
      estadoGps = "ok";
      ponto = {
        lat: pos.coords.latitude, lon: pos.coords.longitude,
        rotulo: "Onde você está", origem: "gps", precisaoM: pos.coords.accuracy,
      };
      window.ORCA_painel?.posicaoAparelho?.(ponto.lat, ponto.lon);
      await consultar();
    } catch (e) {
      console.warn("Localização indisponível:", e);
      estadoGps = "negado";
      if (ponto) await consultar();
      else desenhar();
    }
  }

  async function consultar() {
    if (!ponto || consultando) return;
    consultando = true;
    desenharVeredito({ carregando: "Consultando a chuva…" });
    await carregarIndice();
    proximos = indice ? calc().setoresProximos(indice, ponto.lat, ponto.lon) : [];

    let falhouChuva = false;
    try {
      const series = await buscarChuvaVariosPontos([
        { lat: ponto.lat, lon: ponto.lon },
        ...proximos.map(p => ({ lat: p.setor.lat, lon: p.setor.lon })),
      ]);
      seriePonto = series[0];
      seriesSetores = series.slice(1);
    } catch (e) {
      console.warn("Open-Meteo indisponível para Perto de mim:", e);
      falhouChuva = true;
      seriePonto = null;
      seriesSetores = proximos.map(() => null);
    }
    consultando = false;

    // Sem índice E sem chuva quase sempre é sem rede: a última consulta guardada
    // diz mais do que dois avisos de erro.
    const semRede = falhouChuva && erroIndice;
    if (semRede && mostrarUltimo("Sem conexão")) return;

    consultadoEm = Date.now();
    const modelo = montarModelo();
    desenhar(modelo);
    if (semRede) aviso("Sem conexão e sem consulta anterior neste aparelho.");
    // Só consulta com dado vira "última consulta": guardar um "Sem dado" faria a
    // tela sem rede mostrar "Sem dado" no lugar do último resultado bom.
    else if (modelo.ponto.estado !== "sem-dado") guardar(modelo);
  }

  /* ------------------------------------------------------------ modelo */

  function analisar(serie, janela, limiar) {
    const agora = Date.now();
    const ref = referenciaObservada(serie, agora);
    const observadoMm = chuvaAcumulada(serie, ref, janela);
    const trajetoria = calc().trajetoria(serie, ref, janela);
    return { ...calc().veredito({ observadoMm, trajetoria, limiar }), observadoMm, refMs: ref };
  }

  function montarModelo() {
    const { janela, limiar } = criterio();
    const v = seriePonto
      ? analisar(seriePonto, janela, limiar)
      : { ...calc().veredito({ observadoMm: null, trajetoria: [], limiar }), observadoMm: null, refMs: null };

    const itens = proximos.map((p, i) => {
      const s = seriesSetores[i];
      let r;
      let nota = "";
      if (s) {
        r = analisar(s, janela, limiar);
      } else {
        const publicado = p.setor[janela === 24 ? "chuva_24h" : "chuva_72h"];
        r = { ...calc().veredito({ observadoMm: publicado, trajetoria: [], limiar }), observadoMm: publicado };
        const ref = referenciaPorUf[p.setor.uf];
        nota = `previsão indisponível${ref ? ` · dado de ${dataHoraBrasilia(Date.parse(ref))}` : ""}`;
      }
      return {
        num: p.setor.num_setor, uf: p.setor.uf, munic: p.setor.munic, grau: p.setor.grau_risco,
        distanciaKm: p.distanciaKm, direcao: p.direcao, dentro: p.dentro,
        estado: r.estado, observadoMm: r.observadoMm, quandoMs: r.quandoMs, nota,
      };
    });

    return {
      rotulo: ponto.rotulo, origem: ponto.origem, precisaoM: ponto.precisaoM,
      janela, limiar, consultadoEm,
      ponto: { estado: v.estado, observadoMm: v.observadoMm, picoMm: v.picoMm, quandoMs: v.quandoMs,
               previsaoIndisponivel: v.previsaoIndisponivel, refMs: v.refMs },
      foraDeSetor: !proximos.some(p => p.dentro),
      listaIndisponivel: erroIndice,
      itens,
    };
  }

  function guardar(modelo) {
    try {
      localStorage.setItem(CHAVE_ULTIMO, JSON.stringify(modelo));
    } catch (e) {
      // sem armazenamento: só não haverá "última consulta" sem rede.
    }
  }

  function lerUltimo() {
    try {
      const m = JSON.parse(localStorage.getItem(CHAVE_ULTIMO) || "null");
      return m && m.ponto && Array.isArray(m.itens) ? m : null;
    } catch (e) {
      return null;
    }
  }

  function mostrarUltimo(motivo) {
    const ultimo = lerUltimo();
    if (!ultimo) return false;
    desenhar(ultimo);
    aviso(`${motivo} · dados de ${dataHoraBrasilia(ultimo.consultadoEm)}`);
    return true;
  }

  /* ------------------------------------------------------------ desenho */

  const TITULOS = {
    "iminente": () => "Risco iminente",
    "previsto": m => {
      const h = Math.max(0, Math.round((m.ponto.quandoMs - Date.now()) / 3600000));
      return `Alerta previsto · em ~${h}h`;
    },
    "sem-alerta": () => "Sem alerta",
    "sem-dado": () => "Sem dado agora",
  };

  function barra(m) {
    const { observadoMm: obs, picoMm: pico } = m.ponto;
    const escala = Math.max(m.limiar * 1.5, obs || 0, pico || 0);
    const pct = v => `${Math.min(100, (v / escala) * 100).toFixed(1)}%`;
    return `<div class="perto-barra" aria-hidden="true">` +
      (typeof pico === "number" ? `<i class="barra-previsto" style="width:${pct(pico)}"></i>` : "") +
      (typeof obs === "number" ? `<i class="barra-agora" style="width:${pct(obs)}"></i>` : "") +
      `<span class="limiar" style="left:${pct(m.limiar)}"></span></div>` +
      `<div class="perto-barra-rotulos"><span>${mm(obs)} agora</span><span>limiar ${m.limiar} mm</span>` +
      `<span>${typeof pico === "number" ? `${mm(pico)} prev.` : "sem previsão"}</span></div>`;
  }

  function desenharVeredito({ carregando } = {}) {
    const caixa = el("pertoVeredito");
    caixa.className = "perto-veredito carregando";
    caixa.innerHTML = `<p class="perto-carregando">${escaparHtml(carregando)}</p>`;
  }

  function desenharConvite(texto, botao) {
    const caixa = el("pertoVeredito");
    caixa.className = "perto-veredito convite";
    caixa.innerHTML = `<p>${escaparHtml(texto)}</p>` +
      (botao ? `<button type="button" class="perto-botao" data-localizar>${escaparHtml(botao)}</button>` : "");
    el("pertoListaBloco").hidden = true;
  }

  function desenhar(modelo) {
    if (!modelo) {
      if (estadoGps === "negado") {
        desenharConvite("Não deu para usar a sua localização. Busque a cidade na barra acima.", "Tentar de novo");
      } else {
        desenharConvite(
          "O ORCA usa a sua localização só neste aparelho, para achar setores e a chuva onde você está.",
          "Usar minha localização");
      }
      return;
    }
    aviso("");
    const m = modelo;
    const p = m.ponto;
    const caixa = el("pertoVeredito");
    caixa.className = `perto-veredito ${p.estado}`;
    let frase;
    if (p.estado === "sem-dado") {
      frase = "Não deu para consultar a chuva deste ponto agora. Tente de novo em instantes.";
    } else {
      frase = `Choveu ${mm(p.observadoMm)} em ${m.janela}h. Limiar ${m.limiar} mm.` +
        (p.previsaoIndisponivel ? " Previsão indisponível." :
          typeof p.picoMm === "number" ? ` Pico previsto em 72h: ${mm(p.picoMm)}.` : "");
    }
    const precisao = m.origem === "gps" && m.precisaoM > 1000
      ? ` · precisão de ~${formatarDistancia(m.precisaoM / 1000)}` : "";
    caixa.innerHTML =
      `<small>${escaparHtml(m.rotulo)}${precisao}</small>` +
      `<strong>${escaparHtml(TITULOS[p.estado](m))}</strong>` +
      `<p>${escaparHtml(frase)}</p>` +
      (p.estado !== "sem-dado" ? barra(m) : "") +
      (m.foraDeSetor ? `<p class="perto-nota">Este ponto não é setor mapeado pela CPRM. O alerta é pela chuva.</p>` : "") +
      (p.refMs ? `<p class="perto-nota">Chuva até ${horaBrasilia(p.refMs)} (Open-Meteo).</p>` : "");

    const bloco = el("pertoListaBloco");
    const lista = el("pertoLista");
    const vazio = el("pertoVazio");
    bloco.hidden = false;
    el("pertoContagem").textContent = m.itens.length ? `${m.itens.length} até 10 km` : "";
    if (m.listaIndisponivel) {
      lista.innerHTML = "";
      vazio.textContent = "Lista de setores indisponível agora.";
      vazio.hidden = false;
      return;
    }
    if (!m.itens.length) {
      lista.innerHTML = "";
      vazio.textContent = "Nenhum setor mapeado pela CPRM a menos de 10 km.";
      vazio.hidden = false;
      return;
    }
    vazio.hidden = true;
    lista.innerHTML = m.itens.map(it => {
      const etiqueta = it.estado === "iminente" ? `<span class="tag iminente">Acima</span>` :
        it.estado === "previsto" ? `<span class="tag previsto">Previsto</span>` : "";
      const onde = it.dentro ? "você está dentro ou junto"
        : `${formatarDistancia(it.distanciaKm)} ${escaparHtml(it.direcao)}`;
      return `<li><button type="button" class="perto-item ${it.estado}" data-uf="${escaparHtml(it.uf)}" ` +
        `data-munic="${escaparHtml(it.munic)}" data-num="${escaparHtml(it.num)}">` +
        `<span class="faixa"></span>` +
        `<span class="texto"><b>${escaparHtml(it.munic)} · <span class="mono">${escaparHtml(it.num)}</span></b>` +
        `<span>${etiqueta} ${escaparHtml(rotuloGrau(it.grau))} · ${mm(it.observadoMm)} / ${m.limiar} mm</span>` +
        (it.nota ? `<span class="nota">${escaparHtml(it.nota)}</span>` : "") + `</span>` +
        `<span class="onde">${onde}</span></button></li>`;
    }).join("");
  }

  /* ------------------------------------------------------------ fluxo */

  async function entrar() {
    if (!window.ORCA.movel?.ehCelular()) return;
    const recente = consultadoEm && Date.now() - consultadoEm < RECONSULTAR_APOS_MS;
    if (recente) return;
    if (!consultadoEm) mostrarUltimo("Última consulta");
    if (ponto && ponto.origem === "municipio" && estadoGps !== "ok") { await consultar(); return; }
    if (await permissaoGps() === "granted") { await localizar(); return; }
    if (!consultadoEm && !lerUltimo()) desenhar(null);
    else if (!consultadoEm) {
      // Há resultado antigo na tela: o convite vai no aviso, sem apagá-lo.
      el("pertoVeredito").insertAdjacentHTML("beforeend",
        `<button type="button" class="perto-botao" data-localizar>Usar minha localização</button>`);
    }
  }

  function ligar() {
    el("vistaPerto").addEventListener("click", ev => {
      if (ev.target.closest("[data-localizar]")) { localizar(); return; }
      const item = ev.target.closest("button.perto-item");
      if (!item) return;
      window.ORCA_painel?.abrirSetor?.(item.dataset.uf, item.dataset.munic, item.dataset.num);
      window.ORCA.movel?.irPara("mapa");
    });
    el("pertoLocalizar").addEventListener("click", () => localizar());

    document.addEventListener("orca:vista", ev => {
      if (ev.detail.vista === "perto") entrar();
    });
    document.addEventListener("orca:criterio", () => {
      if (consultadoEm && ponto) desenhar(montarModelo());
    });
    document.addEventListener("orca:municipio", ev => {
      if (window.ORCA.movel?.vistaAtual() !== "perto") return;
      if (estadoGps === "ok") return;
      const d = ev.detail;
      ponto = { lat: d.lat, lon: d.lon, rotulo: `Centro de ${d.nome}, ${d.uf.toUpperCase()}`, origem: "municipio" };
      consultar();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") return;
      if (window.ORCA.movel?.vistaAtual() !== "perto") return;
      if (consultadoEm && Date.now() - consultadoEm > RECONSULTAR_APOS_MS) consultar();
    });

    // A primeira aba é decidida por movel.js antes deste script ligar os
    // ouvintes; e o critério só existe depois do script principal.
    document.addEventListener("DOMContentLoaded", () => {
      if (window.ORCA.movel?.vistaAtual() === "perto") entrar();
    });
  }

  ligar();
})();
