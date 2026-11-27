(function () {
  "use strict";

  const { escaparHtml } = window.ORCA;

  // Formato normalizado consumido por este módulo:
  // { nome, tipo, classificacao, chuva24, chuva72, distanciaKm, fonteEstacao,
  //   fonte, licenca, orgao, sobrepoeCprm, repetidoNaCprm, trajetoria }
  // trajetoria é opcional: [[isoDate, mmOuNull], ...]
  // fonte/licenca/orgao vêm do levantamento que mapeou o setor; sobrepoeCprm é
  // true, false ou null (não se aplica: o setor é da própria CPRM).

  function formatarMm(valor) {
    return typeof valor === "number" ? `${valor.toFixed(1)}mm` : "—";
  }

  function campoCSV(valor) {
    return `"${String(valor == null ? "" : valor).replace(/"/g, '""')}"`;
  }

  function arredondar2(valor) {
    return typeof valor === "number" ? Math.round(valor * 100) / 100 : valor;
  }

  /* `sobrepoeCprm` tem três valores no CSV, como no dado: "sim", "nao" e vazio
     (não se aplica, porque o setor é da própria CPRM). */
  function sobreposicaoCSV(it) {
    if (it.sobrepoeCprm === true) return "sim";
    if (it.sobrepoeCprm === false) return "nao";
    return "";
  }

  function paraCSV(itens) {
    const colunas = ["nome", "tipo", "classificacao", "chuva_24h_mm", "chuva_72h_mm", "distancia_km",
      "fonte_estacao", "fonte_setor", "orgao_setor", "licenca_setor", "sobrepoe_cprm", "contado"];
    const linhas = itens.map(it =>
      [it.nome, it.tipo, it.classificacao || "sem grau", arredondar2(it.chuva24), arredondar2(it.chuva72),
        arredondar2(it.distanciaKm), it.fonteEstacao, it.fonte, it.orgao, it.licenca,
        sobreposicaoCSV(it), it.repetidoNaCprm ? "nao" : "sim"]
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
    // Revogar logo após o click pode abortar o download (Safari/Firefox); o
    // FileSaver.js espera 40s pelo mesmo motivo. O blob é pequeno.
    setTimeout(() => URL.revokeObjectURL(url), 40000);
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
      // "sem grau" impresso, e não a linha omitida: setor sem classificação
      // existe (Belo Horizonte publica 804 deles) e omitir a linha fazia o PDF
      // parecer incompleto em vez de dizer o que a fonte diz.
      ["Classificação", item.classificacao || "sem grau"],
      ["Chuva 24h", formatarMm(item.chuva24)],
      ["Chuva 72h", formatarMm(item.chuva72)],
      typeof item.distanciaKm === "number" ? ["Distância da estação", `${item.distanciaKm.toFixed(1)}km`] : null,
      item.fonteEstacao ? ["Fonte da chuva", item.fonteEstacao] : null,
      item.orgao ? ["Órgão do mapeamento", item.orgao] : null,
      item.licenca ? ["Licença do mapeamento", item.licenca] : null,
      item.sobrepoeCprm === true ? ["Também mapeado pela CPRM", "sim"] : null,
      item.repetidoNaCprm
        ? ["Na contagem", "não somado: mais da metade da área já está mapeada pela CPRM"] : null,
    ].filter(Boolean);

    return (
      `<h2>${escaparHtml(item.nome)}</h2>` +
      `<table>${linhas.map(([rotulo, valor]) => `<tr><td>${escaparHtml(rotulo)}</td><td>${escaparHtml(valor)}</td></tr>`).join("")}</table>` +
      linhaTrajetoria
    );
  }

  /* Crédito de quem mapeou os setores DESTE recorte, com a licença de cada um.
     Sai dos próprios itens, e não de uma lista fixa: fonte de licença
     compartilha-igual (a ODbL do Recife) obriga quem redistribui, então o
     relatório tem de dizer de onde cada setor veio. */
  function creditoFontes(itens) {
    const vistas = new Map();
    for (const it of itens) {
      if (!it.fonte || vistas.has(it.fonte)) continue;
      vistas.set(it.fonte, it.licenca || "licença não declarada pela fonte");
    }
    const partes = [...vistas].map(([fonte, licenca]) => `${fonte} (${licenca})`);
    // Área enviada pelo usuário não tem fonte de setor: nesse caso o relatório
    // não credita mapeamento nenhum, em vez de creditar a CPRM por engano.
    return (partes.length ? `Setores: ${partes.join("; ")}. ` : "") +
      "Chuva: Open-Meteo (CC-BY 4.0). Município e malha: IBGE. " +
      "ORCA sob AGPL-3.0-or-later";
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
      `<p class="rodape">Gerado em ${escaparHtml(agora)} · ${escaparHtml(creditoFontes(itens))} · ` +
      `hcristosm.github.io/ORCA</p>` +
      itens.map(blocoRelatorioHTML).join("") +
      `</body></html>`;

    janela.document.write(html);
    janela.document.close();
    // Direto, não em `onload`: atribuído depois do close(), o load pode já ter
    // passado. A página não tem recurso externo para esperar.
    janela.focus();
    janela.print();
  }

  window.ORCA_relatorio = { paraCSV, exportarCSV, abrirRelatorioImpressao, creditoFontes };
})();
