/* Service worker do ORCA: abre sem sinal com a casca do app e os últimos dados.

   Estratégia:
   - mesma origem (HTML, JS, CSS, data/*.json): rede primeiro, com 4 s de
     limite; se a rede responde, atualiza o cache; se falha ou demora, serve o
     cache. Rede primeiro dispensa esquema de versões: a casca nova chega na
     primeira carga com rede.
   - bibliotecas de CDN (unpkg, jsdelivr): cache primeiro (as URLs têm versão
     fixa, então nunca mudam).
   - todo o resto (tiles, Open-Meteo, INMET, radar, raios) passa direto: dado
     ao vivo velho é pior que dado ausente, e a página já trata a ausência.

   Os GeoJSON por UF (49 MB) NÃO são pré-carregados: entram no cache só quando
   a pessoa visita aquela UF. */
"use strict";

const CACHE_CASCA = "orca-casca-v1";
const CACHE_CDN = "orca-cdn-v1";
const CACHES_ATUAIS = [CACHE_CASCA, CACHE_CDN];
const LIMITE_REDE_MS = 4000;

const CASCA = [
  "./",
  "index.html",
  "style.css",
  "comum.js",
  "calculo.js",
  "movel.js",
  "perto.js",
  "relatorio.js",
  "areas-customizadas.js",
  "manifest.webmanifest",
  "icons/sprite.svg",
  "icons/app-192.png",
  "logo/orca-logo-claro.png",
  "logo/orca-logo-escuro.png",
  "fonts/plex-sans.woff2",
  "fonts/plex-cond-600.woff2",
  "fonts/plex-cond-700.woff2",
  "fonts/plex-mono-400.woff2",
  "fonts/plex-mono-500.woff2",
  "data/ufs_disponiveis.json",
  "data/setores_pontos.json",
];

const CDN = [
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
  "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js",
  "https://unpkg.com/shpjs@4.0.4/dist/shp.min.js",
  "https://unpkg.com/@tmcw/togeojson@5.8.1/dist/togeojson.umd.js",
];
const HOSTS_CDN = ["unpkg.com", "cdn.jsdelivr.net"];

/* Um item que falhe (ex.: índice ausente hoje) não pode impedir a instalação. */
async function precarregar(nomeCache, urls) {
  const cache = await caches.open(nomeCache);
  await Promise.allSettled(urls.map(async url => {
    const resp = await fetch(new Request(url, { mode: "cors", cache: "reload" }));
    if (resp.ok) await cache.put(url, resp);
  }));
}

self.addEventListener("install", ev => {
  ev.waitUntil(Promise.all([precarregar(CACHE_CASCA, CASCA), precarregar(CACHE_CDN, CDN)]));
  self.skipWaiting();
});

self.addEventListener("activate", ev => {
  ev.waitUntil((async () => {
    const nomes = await caches.keys();
    await Promise.all(nomes
      .filter(n => n.startsWith("orca-") && !CACHES_ATUAIS.includes(n))
      .map(n => caches.delete(n)));
    await self.clients.claim();
  })());
});

async function redePrimeiro(req) {
  const cache = await caches.open(CACHE_CASCA);
  const daRede = fetch(req).then(resp => {
    if (resp.ok) cache.put(req, resp.clone());
    return resp;
  });
  const limite = new Promise(resolve => setTimeout(() => resolve(null), LIMITE_REDE_MS));
  try {
    const resp = await Promise.race([daRede, limite]);
    if (resp) return resp;
  } catch (e) {
    // rede fora: cai no cache abaixo.
  }
  // Ignora a query (?t=, ?r=) para achar a mesma página/arquivo no cache.
  const guardado = await cache.match(req, { ignoreSearch: true });
  if (guardado) return guardado;
  return daRede;  // sem cache: devolve o que a rede der (ou o erro dela).
}

async function cachePrimeiro(req) {
  const cache = await caches.open(CACHE_CDN);
  const guardado = await cache.match(req);
  if (guardado) return guardado;
  const resp = await fetch(req);
  if (resp.ok || resp.type === "opaque") cache.put(req, resp.clone());
  return resp;
}

self.addEventListener("fetch", ev => {
  const req = ev.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // A sonda de "aba parada" do index.html pergunta se HÁ rede; responder do
  // cache a faria recarregar sem sinal. Passa direto.
  if (url.searchParams.has("sonda")) return;
  if (url.origin === self.location.origin) {
    ev.respondWith(redePrimeiro(req));
  } else if (HOSTS_CDN.includes(url.hostname)) {
    ev.respondWith(cachePrimeiro(req));
  }
});
