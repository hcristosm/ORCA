/* Cálculos sem DOM do ORCA no celular: geometria do toque, distância,
   setores próximos e veredito de um ponto.

   Sem DOM de propósito: é o que a etapa 2 (app nativo, aviso em segundo
   plano) vai reusar fora da página. Testes em tests/js/calculo.html. */
(function () {
  "use strict";

  /* Distância de `p` ao segmento a–b, no mesmo plano (pixels de tela). */
  function distanciaPontoSegmento(p, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const comprimento2 = dx * dx + dy * dy;
    let t = comprimento2 ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / comprimento2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
  }

  /* 0 se `p` está dentro do polígono (regra par-ímpar sobre todos os anéis,
     então furos ficam fora); senão, a menor distância até uma aresta. */
  function distanciaPontoPoligonoPx(p, aneis) {
    let dentro = false;
    let menor = Infinity;
    for (const anel of aneis) {
      const n = anel.length;
      for (let i = 0, j = n - 1; i < n; j = i++) {
        const a = anel[i];
        const b = anel[j];
        if ((a.y > p.y) !== (b.y > p.y) &&
            p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x) {
          dentro = !dentro;
        }
        menor = Math.min(menor, distanciaPontoSegmento(p, a, b));
      }
    }
    return dentro ? 0 : menor;
  }

  /* ------------------------------------------------ distância e direção */

  const RAIO_TERRA_KM = 6371;
  const rad = g => (g * Math.PI) / 180;

  function distanciaKm(lat1, lon1, lat2, lon2) {
    const dLat = rad(lat2 - lat1);
    const dLon = rad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
    return 2 * RAIO_TERRA_KM * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  const ROSA = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"];

  /* Rumo de quem está em (latDe, lonDe) até (latPara, lonPara), em 8 setores de 45°. */
  function direcaoCardinal(latDe, lonDe, latPara, lonPara) {
    const y = Math.sin(rad(lonPara - lonDe)) * Math.cos(rad(latPara));
    const x = Math.cos(rad(latDe)) * Math.sin(rad(latPara)) -
      Math.sin(rad(latDe)) * Math.cos(rad(latPara)) * Math.cos(rad(lonPara - lonDe));
    const graus = ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
    return ROSA[Math.round(graus / 45) % 8];
  }

  /* -------------------------------------------- índice de setores (Tarefa 4) */

  const VERSAO_INDICE = 1;
  const CAMPOS_INDICE = [
    "num_setor", "uf", "munic", "grau_risco", "lat", "lon",
    "oeste", "sul", "leste", "norte", "chuva_24h", "chuva_72h",
  ];

  /* Lê setores_pontos.json. Monta cada setor pelo nome do campo (não pela
     posição), para um campo novo no fim ou reordenado não trocar os valores. */
  function lerIndice(json) {
    if (!json || json.versao !== VERSAO_INDICE) {
      throw new Error(`Índice de setores com versão desconhecida: ${json && json.versao}.`);
    }
    const campos = Array.isArray(json.campos) ? json.campos : [];
    const faltando = CAMPOS_INDICE.filter(c => !campos.includes(c));
    if (faltando.length) throw new Error(`Índice de setores sem os campos: ${faltando.join(", ")}.`);
    if (!Array.isArray(json.setores)) throw new Error("Índice de setores sem a lista de setores.");
    const pos = Object.fromEntries(CAMPOS_INDICE.map(c => [c, campos.indexOf(c)]));
    return json.setores.map(linha => ({
      num_setor: linha[pos.num_setor],
      uf: linha[pos.uf],
      munic: linha[pos.munic],
      grau_risco: linha[pos.grau_risco],
      lat: linha[pos.lat],
      lon: linha[pos.lon],
      caixa: [linha[pos.oeste], linha[pos.sul], linha[pos.leste], linha[pos.norte]],
      chuva_24h: linha[pos.chuva_24h],
      chuva_72h: linha[pos.chuva_72h],
    }));
  }

  /* Setores a até `raioKm` do centroide, ou cuja caixa contém o ponto
     (`dentro`: setor grande com centroide longe ainda é o lugar onde se está).
     Os de `dentro` vêm primeiro; depois, pela distância. */
  function setoresProximos(setores, lat, lon, { raioKm = 10, max = 5 } = {}) {
    const candidatos = [];
    for (const setor of setores) {
      const [oeste, sul, leste, norte] = setor.caixa;
      const dentro = lon >= oeste && lon <= leste && lat >= sul && lat <= norte;
      const d = distanciaKm(lat, lon, setor.lat, setor.lon);
      if (!dentro && d > raioKm) continue;
      candidatos.push({ setor, distanciaKm: d, direcao: direcaoCardinal(lat, lon, setor.lat, setor.lon), dentro });
    }
    candidatos.sort((a, b) => (b.dentro - a.dentro) || (a.distanciaKm - b.distanciaKm));
    return candidatos.slice(0, max);
  }

  /* -------------------------------------------------- trajetória e veredito */

  const HORA_MS = 3600 * 1000;

  /* Espelha src/processing/previsao.py::trajetoria_chuva_72h com a janela como
     parâmetro: em cada t = agora + k·passo, a soma da janela (t − janela, t].
     t além do último ponto com valor numérico vira null (não decai rumo a 0). */
  function trajetoria(serie, agoraMs, janelaHoras, { passoHoras = 3, horizonteHoras = 72 } = {}) {
    const acumulada = window.ORCA.chuvaAcumulada;
    const validos = serie.filter(p => typeof p.chuvaMm === "number");
    const ultimo = validos.length ? Math.max(...validos.map(p => p.dataHoraMs)) : -Infinity;
    const pontos = [];
    for (let h = 0; h <= horizonteHoras; h += passoHoras) {
      const t = agoraMs + h * HORA_MS;
      pontos.push([t, t > ultimo ? null : acumulada(serie, t, janelaHoras)]);
    }
    return pontos;
  }

  /* Regras, em ordem: sem observado → sem-dado; observado ≥ limiar → iminente;
     primeiro ponto da trajetória ≥ limiar → previsto; senão, sem-alerta. */
  function veredito({ observadoMm, trajetoria: pontos, limiar }) {
    const numericos = (pontos || []).filter(([, mm]) => typeof mm === "number");
    const picoMm = numericos.length ? Math.max(...numericos.map(([, mm]) => mm)) : null;
    const base = { quandoMs: null, picoMm, previsaoIndisponivel: numericos.length === 0 };
    if (typeof observadoMm !== "number") return { ...base, estado: "sem-dado" };
    if (observadoMm >= limiar) return { ...base, estado: "iminente" };
    const cruza = numericos.find(([, mm]) => mm >= limiar);
    if (cruza) return { ...base, estado: "previsto", quandoMs: cruza[0] };
    return { ...base, estado: "sem-alerta" };
  }

  window.ORCA = Object.assign(window.ORCA || {}, {
    calculo: Object.assign((window.ORCA && window.ORCA.calculo) || {}, {
      distanciaPontoPoligonoPx,
      distanciaKm,
      direcaoCardinal,
      lerIndice,
      setoresProximos,
      trajetoria,
      veredito,
    }),
  });
})();
