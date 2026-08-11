(function () {
  "use strict";

  const LIMITE_AREAS = 5;
  const LIMITE_TAMANHO_BYTES = 10 * 1024 * 1024;

  let areas = [];
  let proximoId = 1;

  function gerarId() {
    return proximoId++;
  }

  document.getElementById("uploadArquivo").addEventListener("change", async ev => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file) return;
    console.log("Arquivo selecionado:", file.name, file.size, "bytes");
  });
})();
