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

  window.ORCA = Object.assign(window.ORCA || {}, { escaparHtml, token });
})();
