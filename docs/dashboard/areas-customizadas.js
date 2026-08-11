(function () {
  "use strict";

  const LIMITE_AREAS = 5;
  const LIMITE_TAMANHO_BYTES = 10 * 1024 * 1024;

  let areas = [];
  let proximoId = 1;

  function gerarId() {
    return proximoId++;
  }

  function normalizarParaFeatureCollection(json) {
    if (Array.isArray(json)) {
      const features = json.flatMap(fc => (fc && fc.features) || []);
      return { type: "FeatureCollection", features };
    }
    if (json && json.type === "FeatureCollection") return json;
    if (json && json.type === "Feature") return { type: "FeatureCollection", features: [json] };
    if (json && json.type && json.coordinates) {
      return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: json }] };
    }
    throw new Error("Arquivo não contém geometria reconhecível (GeoJSON/KML/shapefile).");
  }

  async function parseArquivo(file) {
    const nome = file.name.toLowerCase();

    if (nome.endsWith(".geojson") || nome.endsWith(".json")) {
      const texto = await file.text();
      let json;
      try {
        json = JSON.parse(texto);
      } catch (e) {
        throw new Error("Arquivo GeoJSON inválido: não é um JSON válido.");
      }
      return normalizarParaFeatureCollection(json);
    }

    if (nome.endsWith(".kml")) {
      const texto = await file.text();
      const dom = new DOMParser().parseFromString(texto, "text/xml");
      if (dom.querySelector("parsererror")) {
        throw new Error("Arquivo KML inválido: não foi possível interpretar o XML.");
      }
      return normalizarParaFeatureCollection(toGeoJSON.kml(dom));
    }

    if (nome.endsWith(".zip")) {
      const buffer = await file.arrayBuffer();
      let geojson;
      try {
        geojson = await shp(buffer);
      } catch (e) {
        throw new Error("Shapefile inválido: confira se o .zip contém .shp, .dbf e .shx.");
      }
      return normalizarParaFeatureCollection(geojson);
    }

    throw new Error("Formato não suportado. Use .geojson, .json, .kml ou .zip (shapefile).");
  }

  function extrairGeometrias(featureCollection, limite) {
    const todas = (featureCollection.features || []).filter(f => f && f.geometry);
    return { usadas: todas.slice(0, limite), descartadas: Math.max(0, todas.length - limite) };
  }

  function centroide(feature) {
    const camada = L.geoJSON(feature);
    const centro = camada.getBounds().getCenter();
    return [centro.lat, centro.lng];
  }

  document.getElementById("uploadArquivo").addEventListener("change", async ev => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file) return;

    const erroEl = document.getElementById("uploadErro");
    erroEl.hidden = true;

    if (file.size > LIMITE_TAMANHO_BYTES) {
      erroEl.textContent = `Arquivo maior que ${LIMITE_TAMANHO_BYTES / (1024 * 1024)}MB — não foi carregado.`;
      erroEl.hidden = false;
      return;
    }

    const vagas = LIMITE_AREAS - areas.length;
    if (vagas <= 0) {
      erroEl.textContent = `Limite de ${LIMITE_AREAS} áreas atingido. Remova alguma antes de carregar outra.`;
      erroEl.hidden = false;
      return;
    }

    let featureCollection;
    try {
      featureCollection = await parseArquivo(file);
    } catch (e) {
      erroEl.textContent = e.message || "Não foi possível ler o arquivo.";
      erroEl.hidden = false;
      return;
    }

    const { usadas, descartadas } = extrairGeometrias(featureCollection, vagas);
    if (!usadas.length) {
      erroEl.textContent = "O arquivo não contém nenhuma geometria válida.";
      erroEl.hidden = false;
      return;
    }
    if (descartadas > 0) {
      erroEl.textContent = `Só as primeiras ${usadas.length} área(s) foram carregadas — ${descartadas} descartada(s) pelo limite de ${LIMITE_AREAS}.`;
      erroEl.hidden = false;
    }

    const baseNome = file.name.replace(/\.(geojson|json|kml|zip)$/i, "");
    for (const [i, feature] of usadas.entries()) {
      const props = feature.properties || {};
      const nomePropriedade = props.name || props.Name || props.NOME;
      const area = {
        id: gerarId(),
        nome: nomePropriedade || (usadas.length > 1 ? `${baseNome} — ${i + 1}` : baseNome),
        feature,
        centroide: centroide(feature),
      };
      areas.push(area);
      console.log("Área carregada:", area.id, area.nome, area.centroide);
    }
  });
})();
