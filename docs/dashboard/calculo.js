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

  /* --------------------------------------------------- vocabulário de grau

     A LISTA ÚNICA do grau de risco, em ordem de severidade. Mora aqui (sem
     DOM) porque index.html, perto.js e os testes precisam da mesma: o grau
     "Médio" entrou em produção e ficou invisível justamente porque havia três
     listas separadas, nenhuma vinda do dado.

     Grau ausente é um valor do vocabulário, não um buraco: na interface ele é
     "sem grau". Valor fora da lista continua passando cru, para "não
     reconhecido" não se confundir com "sem grau". */
  const GRAUS = ["Muito alto", "Alto", "Médio", "Baixo", "sem grau"];
  const SEM_GRAU = "sem grau";
  const CHAVES_GRAU = GRAUS.map(g => g.toLowerCase());

  /* Chave canônica do grau (minúscula), para comparar, filtrar e indexar. */
  function chaveGrau(grau) {
    const g = String(grau == null ? "" : grau).trim().toLowerCase();
    return g || SEM_GRAU;
  }

  /* Rótulo do grau como ele aparece na tela. */
  function rotuloGrau(grau) {
    const chave = chaveGrau(grau);
    const conhecido = GRAUS.find(g => g.toLowerCase() === chave);
    return conhecido || (chave.charAt(0).toUpperCase() + chave.slice(1));
  }

  /* Severidade comparável: maior é pior. Grau desconhecido fica em 0, abaixo
     de "sem grau", para nunca ganhar de um grau de verdade na comparação. */
  function severidadeGrau(grau) {
    const i = CHAVES_GRAU.indexOf(chaveGrau(grau));
    return i < 0 ? 0 : GRAUS.length - i;
  }

  /* ------------------------------------------------------- fonte do setor */

  const ID_CPRM = "br-sgb-setorizacao";

  /* Setor da CPRM? Dado antigo não traz `bl_fonte` e é todo da CPRM. */
  function ehCprm(fonte) {
    return !fonte || fonte === ID_CPRM;
  }

  /* `bl_sob_cp` tem TRÊS estados: `true` (a CPRM cobre 1% ou mais da área do
     setor), `false` (conferido e não cobre) e nulo (é setor da própria CPRM, e
     a pergunta não se aplica). Lida de JSON a coluna pode voltar como número,
     então a comparação é `=== true`, nunca truthiness. */
  function sobrepoeCprm(p) {
    return p.bl_sob_cp === true;
  }

  /* Limiar de IDENTIDADE: acima de metade da área coberta, o setor externo é a
     mesma área de risco que um setor da CPRM e não entra duas vezes na conta.
     É pergunta diferente da do 1% do BELUGA, que é de detecção ("existe
     relação entre este setor e a CPRM?") e por isso tem de ser baixa. */
  const LIMIAR_REPETIDO = 0.5;

  /* Setor que já está contado como área de risco pelo levantamento da CPRM.
     Continua no mapa, nas tabelas e nos relatórios: só não é somado de novo. */
  function repetidoNaCprm(p) {
    return !ehCprm(p.bl_fonte) &&
      typeof p.bl_cp_frac === "number" && p.bl_cp_frac > LIMIAR_REPETIDO;
  }

  /* Rótulo curto de uma fonte a partir do id do BELUGA
     ("mg-juiz-de-fora-sspdc" -> "Juiz de Fora (MG)"). Serve de reserva onde o
     nome publicado não está à mão (perto.js lê só o índice de pontos, que
     carrega o id). Onde há `meta_<uf>.json`, o nome dele é que vale. */
  function rotuloFonte(id) {
    if (ehCprm(id)) return "CPRM/SGB";
    const partes = String(id).split("-").filter(Boolean);
    if (partes.length < 3) return String(id);
    const uf = partes[0].toUpperCase();
    const cidade = partes.slice(1, -1)
      .map(t => (t.length <= 2 ? t : t.charAt(0).toUpperCase() + t.slice(1)))
      .join(" ");
    return `${cidade} (${uf})`;
  }

  /* -------------------------------------------- índice de setores (Tarefa 4) */

  const VERSAO_INDICE = 2;
  const CAMPOS_INDICE = [
    "num_setor", "uf", "munic", "grau_risco", "lat", "lon",
    "oeste", "sul", "leste", "norte", "chuva_24h", "chuva_72h",
    "bl_fonte", "bl_produto",
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
      bl_fonte: linha[pos.bl_fonte],
      bl_produto: linha[pos.bl_produto],
    }));
  }

  /* Até onde "você está aqui" vale para um setor que é um ponto, e não um
     polígono. A caixa de um ponto é degenerada (oeste == leste), então a regra
     de contenção nunca daria verdadeiro e o setor cairia só no raio de 10 km,
     como se estivesse longe. */
  const RAIO_PONTO_KM = 0.05;

  /* O ponto (lat, lon) está dentro do setor, ou junto dele?

     Setor com caixa de área nula (ponto de risco, sliver digitalizado) cai na
     regra de proximidade: contenção numa caixa sem largura é sempre falsa. */
  function dentroDoSetor(setor, lat, lon, distanciaAoCentroideKm) {
    const [oeste, sul, leste, norte] = setor.caixa || [];
    const caixaUtil = [oeste, sul, leste, norte].every(Number.isFinite) &&
      leste > oeste && norte > sul;
    if (setor.bl_produto === "ponto_risco" || !caixaUtil) {
      return distanciaAoCentroideKm <= RAIO_PONTO_KM;
    }
    return lon >= oeste && lon <= leste && lat >= sul && lat <= norte;
  }

  /* Setores a até `raioKm` do centroide, ou que contenham o ponto
     (`dentro`: setor grande com centroide longe ainda é o lugar onde se está).
     Os de `dentro` vêm primeiro; depois, pela distância. */
  function setoresProximos(setores, lat, lon, { raioKm = 10, max = 5 } = {}) {
    const candidatos = [];
    for (const setor of setores) {
      const d = distanciaKm(lat, lon, setor.lat, setor.lon);
      const dentro = dentroDoSetor(setor, lat, lon, d);
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
     primeiro ponto da trajetória ≥ limiar → previsto; senão, sem-alerta.

     O 1º ponto da trajetória é "agora" (a hora observada, que é numérica): só
     os pontos SEGUINTES dizem se há previsão. Contar o de agora fazia previsão
     ausente aparecer como "Sem alerta" com pico = o próprio observado. */
  function veredito({ observadoMm, trajetoria: pontos, limiar }) {
    const numericos = (pontos || []).slice(1).filter(([, mm]) => typeof mm === "number");
    const picoMm = numericos.length ? Math.max(...numericos.map(([, mm]) => mm)) : null;
    const base = { quandoMs: null, picoMm, previsaoIndisponivel: numericos.length === 0 };
    if (typeof observadoMm !== "number") return { ...base, estado: "sem-dado" };
    if (observadoMm >= limiar) return { ...base, estado: "iminente" };
    const cruza = numericos.find(([, mm]) => mm >= limiar);
    if (cruza) return { ...base, estado: "previsto", quandoMs: cruza[0] };
    return { ...base, estado: "sem-alerta" };
  }

  /* A falha da consulta parece "sem rede"? fetch rejeita com TypeError quando
     não há conexão, e fetchComTimeout aborta (AbortError) quando ela é lenta
     demais; HTTP de erro com rede é outra coisa (a API caiu, não o aparelho). */
  function pareceSemRede(erro, online) {
    if (online === false) return true;
    return Boolean(erro) && (erro instanceof TypeError || erro.name === "AbortError");
  }

  /* ------------------------------------- município sem setor da CPRM */

  /* A CPRM não grava o código IBGE, só o nome, às vezes com a UF no fim
     ("SÃO MIGUEL DO TOCANTINS (TO)"). Comparar sem acento, caixa e sufixo. */
  function normalizarMunicipio(nome) {
    return String(nome || "")
      .replace(/\(.*?\)/g, " ")
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .toUpperCase()
      .replace(/[^A-Z0-9]+/g, " ")
      .trim();
  }

  /* Grafias antigas da CPRM que não batem com o IBGE (conferido em 2026-11-21
     contra os 1.601 municípios com setor: só estes três). */
  const GRAFIA_CPRM_PARA_IBGE = {
    "mg|BARAO DE MONTE ALTO": "BARAO DO MONTE ALTO",
    "mt|SANTO ANTONIO DO LEVERGER": "SANTO ANTONIO DE LEVERGER",
    "rn|ACU": "ASSU",
  };

  function lerMunicipios(json) {
    const campos = (json && json.campos) || [];
    const i = nome => campos.indexOf(nome);
    return ((json && json.municipios) || []).map(linha => ({
      uf: linha[i("uf")], nome: linha[i("nome")], lat: linha[i("lat")], lon: linha[i("lon")],
    }));
  }

  /* Municípios do IBGE (`lista`) sem nenhum setor da CPRM (`comSetor`, nomes
     da CPRM por UF). Só UF que tem ao menos um nome em `comSetor` entra: UF
     cuja lista não carregou ficaria inteira como "sem setor", o que é falso. */
  function municipiosSemCobertura(lista, comSetor) {
    const cobertos = new Set();
    const ufsConhecidas = new Set();
    for (const { uf, nome } of comSetor) {
      const chave = `${uf}|${normalizarMunicipio(nome)}`;
      ufsConhecidas.add(uf);
      cobertos.add(`${uf}|${GRAFIA_CPRM_PARA_IBGE[chave] || normalizarMunicipio(nome)}`);
    }
    return lista.filter(m =>
      ufsConhecidas.has(m.uf) && !cobertos.has(`${m.uf}|${normalizarMunicipio(m.nome)}`));
  }

  window.ORCA = Object.assign(window.ORCA || {}, {
    calculo: Object.assign((window.ORCA && window.ORCA.calculo) || {}, {
      GRAUS,
      SEM_GRAU,
      ID_CPRM,
      chaveGrau,
      rotuloGrau,
      severidadeGrau,
      ehCprm,
      sobrepoeCprm,
      repetidoNaCprm,
      LIMIAR_REPETIDO,
      rotuloFonte,
      lerMunicipios,
      municipiosSemCobertura,
      normalizarMunicipio,
      pareceSemRede,
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
