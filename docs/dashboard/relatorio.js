(function () {
  "use strict";

  // Formato normalizado consumido por este módulo:
  // { nome, tipo, classificacao, chuva24, chuva72, distanciaKm, fonteEstacao, trajetoria }
  // trajetoria é opcional: [[isoDate, mmOuNull], ...]

  function escaparHtml(texto) {
    const div = document.createElement("div");
    div.textContent = texto == null ? "" : String(texto);
    return div.innerHTML;
  }

  function formatarMm(valor) {
    return typeof valor === "number" ? `${valor.toFixed(1)}mm` : "—";
  }

  function campoCSV(valor) {
    return `"${String(valor == null ? "" : valor).replace(/"/g, '""')}"`;
  }

  function arredondar2(valor) {
    return typeof valor === "number" ? Math.round(valor * 100) / 100 : valor;
  }

  function paraCSV(itens) {
    const colunas = ["nome", "tipo", "classificacao", "chuva_24h_mm", "chuva_72h_mm", "distancia_km", "fonte_estacao"];
    const linhas = itens.map(it =>
      [it.nome, it.tipo, it.classificacao, arredondar2(it.chuva24), arredondar2(it.chuva72), arredondar2(it.distanciaKm), it.fonteEstacao]
        .map(campoCSV)
        .join(",")
    );
    return [colunas.join(","), ...linhas].join("\r\n");
  }

  function baixarArquivo(conteudo, nomeArquivo, tipoMime) {
    const blob = new Blob([conteudo], { type: tipoMime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = nomeArquivo;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function exportarCSV(itens, nomeArquivo) {
    baixarArquivo(paraCSV(itens), nomeArquivo, "text/csv;charset=utf-8");
  }

  function blocoRelatorioHTML(item) {
    const linhaTrajetoria = Array.isArray(item.trajetoria) && item.trajetoria.length
      ? `<h3>Trajetória prevista (72h)</h3><table>` +
        item.trajetoria.map(([iso, mm]) =>
          `<tr><td>${escaparHtml(new Date(iso).toLocaleString("pt-BR"))}</td><td>${formatarMm(mm)}</td></tr>`
        ).join("") +
        `</table>`
      : "";

    const linhas = [
      ["Tipo", item.tipo],
      item.classificacao ? ["Classificação", item.classificacao] : null,
      ["Chuva 24h", formatarMm(item.chuva24)],
      ["Chuva 72h", formatarMm(item.chuva72)],
      typeof item.distanciaKm === "number" ? ["Distância da estação", `${item.distanciaKm.toFixed(1)}km`] : null,
      item.fonteEstacao ? ["Fonte da chuva", item.fonteEstacao] : null,
    ].filter(Boolean);

    return (
      `<h2>${escaparHtml(item.nome)}</h2>` +
      `<table>${linhas.map(([rotulo, valor]) => `<tr><td>${escaparHtml(rotulo)}</td><td>${escaparHtml(valor)}</td></tr>`).join("")}</table>` +
      linhaTrajetoria
    );
  }

  function abrirRelatorioImpressao(itens, titulo) {
    const janela = window.open("", "_blank");
    if (!janela) return;

    const agora = new Date().toLocaleString("pt-BR");
    const html =
      `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${escaparHtml(titulo)}</title>` +
      `<style>
        body { font-family: system-ui, sans-serif; color: #111; margin: 2rem; }
        h1 { font-size: 1.3rem; margin-bottom: .25rem; }
        h2 { font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #ccc; padding-bottom: .25rem; }
        h3 { font-size: .9rem; margin-top: 1rem; }
        table { border-collapse: collapse; width: 100%; margin-bottom: .5rem; }
        td, th { padding: .3rem .5rem; text-align: left; border-bottom: 1px solid #eee; font-size: .9rem; }
        .rodape { margin-top: 2rem; font-size: .75rem; color: #666; }
        @media print { .rodape { position: fixed; bottom: 0; } }
      </style></head><body>` +
      `<h1>${escaparHtml(titulo)}</h1>` +
      `<p class="rodape">Gerado em ${escaparHtml(agora)} · dados públicos CPRM/SGB + Open-Meteo/INMET/ANA · hcristosm.github.io/ORCA</p>` +
      itens.map(blocoRelatorioHTML).join("") +
      `</body></html>`;

    janela.document.write(html);
    janela.document.close();
    janela.onload = () => janela.print();
  }

  window.ORCA_relatorio = { paraCSV, exportarCSV, abrirRelatorioImpressao };
})();
