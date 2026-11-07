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

  window.ORCA = Object.assign(window.ORCA || {}, {
    calculo: Object.assign((window.ORCA && window.ORCA.calculo) || {}, {
      distanciaPontoPoligonoPx,
    }),
  });
})();
