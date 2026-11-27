/* Casca do celular (< 768 px): barra fina, abas embaixo e gaveta de ajustes.

   Não clona nada: move os nós que já existem (busca, critério, janela, régua,
   controle de camadas) para a barra e a gaveta, deixando um comentário-âncora
   no lugar de cada um. Ao voltar para o desktop, cada nó volta para antes da
   sua âncora. Assim os ouvintes do index.html continuam valendo nos dois
   tamanhos, e o desktop fica idêntico.

   Carrega ANTES do script principal do index.html: a aba inicial depende do
   hash com que a página abriu, e o script principal reescreve o hash com a
   última visita guardada. */
(function () {
  "use strict";

  const MQ = window.matchMedia("(max-width: 767px)");
  const VISTAS = ["perto", "mapa", "alertas", "mais"];

  function paramsDoHash(hash) {
    const [caminho, consulta] = hash.replace(/^#\/?/, "").split("?");
    return { partes: (caminho || "").split("/").filter(Boolean), params: new URLSearchParams(consulta || "") };
  }

  /* Hash com `v` usa o `v`; com município (#/uf/municipio) vai ao mapa; sem
     município ou sem hash, "Perto de mim". */
  function vistaDoHash(hash) {
    const { partes, params } = paramsDoHash(hash);
    const v = params.get("v");
    if (VISTAS.includes(v)) return v;
    return partes.length >= 2 ? "mapa" : "perto";
  }

  let vista = vistaDoHash(location.hash);

  function gravarVistaNoHash() {
    const [caminho, consulta] = location.hash.replace(/^#/, "").split("?");
    const params = new URLSearchParams(consulta || "");
    if (params.get("v") === vista) return;
    params.set("v", vista);
    try {
      history.replaceState(history.state, "", `#${caminho || "/"}?${params}`);
    } catch (e) {
      // history indisponível (sandbox): a aba na tela continua certa.
    }
  }

  // ------------------------------------------------------------ mover nós

  const ancoras = new Map();

  function mover(no, destino) {
    if (!no || !destino || ancoras.has(no)) return;
    const ancora = document.createComment("lugar de origem (movel.js)");
    no.before(ancora);
    ancoras.set(no, ancora);
    destino.append(no);
  }

  function restaurarTodos() {
    for (const [no, ancora] of ancoras) {
      if (ancora.isConnected) ancora.replaceWith(no);
      else no.remove();
    }
    ancoras.clear();
  }

  let camadasMovidas = null;

  /* O controle de camadas é recriado a cada mapa novo (troca de UF, Voltar):
     o antigo morre com o mapa velho, e o novo precisa ir para a gaveta de novo. */
  function moverCamadas() {
    if (camadasMovidas) {
      const ancora = ancoras.get(camadasMovidas);
      ancoras.delete(camadasMovidas);
      if (ancora) ancora.remove();
      camadasMovidas = null;
    }
    if (!MQ.matches) return;
    const controle = window.ORCA_painel?.controleCamadas?.();
    const caixa = controle && controle.getContainer();
    if (!caixa) return;
    let alvo = document.getElementById("gavetaCamadas");
    if (!alvo) {
      alvo = document.createElement("section");
      alvo.id = "gavetaCamadas";
      alvo.className = "gaveta-camadas";
      alvo.innerHTML = "<h3>Camadas do mapa</h3>";
      document.getElementById("gavetaCorpo").append(alvo);
    }
    mover(caixa, alvo);
    camadasMovidas = caixa;
  }

  function entrarNoCelular() {
    const corpo = document.getElementById("gavetaCorpo");
    mover(document.querySelector(".faceplate .busca"), document.getElementById("barraBusca"));
    mover(document.querySelector(".campo-uf"), corpo);
    mover(document.querySelector(".campo-criterio"), corpo);
    mover(document.getElementById("janelaToggle")?.closest(".campo"), corpo);
    mover(document.querySelector(".bloco-regua"), corpo);
    moverCamadas();
    aplicarVista();
  }

  function sairDoCelular() {
    fecharGaveta(false);
    restaurarTodos();
    camadasMovidas = null;
    document.getElementById("gavetaCamadas")?.remove();
    delete document.body.dataset.vistaMovel;
    delete document.body.dataset.subMais;
    document.getElementById("vistaPerto").hidden = true;
    document.getElementById("vistaMais").hidden = true;
    // Volta à aba de desktop que estava aberta (a de "Mais" pode ter trocado).
    window.ORCA_painel?.mapaMudouDeTamanho?.();
  }

  // ------------------------------------------------------------ abas

  function abaDesktop(id) {
    const botao = document.querySelector(`#abas button[data-vista="${id}"]`);
    if (botao && !botao.classList.contains("ativo")) botao.click();
  }

  function aplicarVista() {
    if (!MQ.matches) return;
    const body = document.body;
    body.dataset.vistaMovel = vista;
    if (vista !== "mais") {
      delete body.dataset.subMais;
      abaDesktop("vistaMapa");
    }
    document.getElementById("vistaPerto").hidden = vista !== "perto";
    document.getElementById("vistaMais").hidden = vista !== "mais" || Boolean(body.dataset.subMais);
    document.querySelectorAll("#abasMovel button").forEach(b => {
      const ativo = b.dataset.vistaMovel === vista;
      b.classList.toggle("ativo", ativo);
      if (ativo) b.setAttribute("aria-current", "page");
      else b.removeAttribute("aria-current");
    });
    gravarVistaNoHash();
    // O mapa pode ter nascido escondido (0x0): o Leaflet só se acerta se mandarem medir.
    if (vista === "mapa") requestAnimationFrame(() => window.ORCA_painel?.mapaMudouDeTamanho?.());
    document.dispatchEvent(new CustomEvent("orca:vista", { detail: { vista } }));
  }

  function irPara(nova) {
    if (!VISTAS.includes(nova)) return;
    vista = nova;
    if (nova === "mais") delete document.body.dataset.subMais;
    aplicarVista();
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ gaveta

  let gavetaNoHistorico = false;

  function abrirGaveta() {
    const gaveta = document.getElementById("gaveta");
    if (!gaveta.hidden) return;
    gaveta.hidden = false;
    document.getElementById("gavetaVeu").hidden = false;
    document.getElementById("barraAjustes").setAttribute("aria-expanded", "true");
    document.body.classList.add("gaveta-aberta");
    // Entrada no histórico para o Voltar do Android fechar a gaveta, e não sair da página.
    try {
      history.pushState({ gaveta: true }, "", location.href);
      gavetaNoHistorico = true;
    } catch (e) {
      gavetaNoHistorico = false;
    }
    document.getElementById("gavetaFechar").focus();
  }

  function fecharGaveta(voltarHistorico = true) {
    const gaveta = document.getElementById("gaveta");
    if (gaveta.hidden) return;
    gaveta.hidden = true;
    gaveta.style.transform = "";
    document.getElementById("gavetaVeu").hidden = true;
    document.getElementById("barraAjustes").setAttribute("aria-expanded", "false");
    document.body.classList.remove("gaveta-aberta");
    if (gavetaNoHistorico && voltarHistorico) {
      gavetaNoHistorico = false;
      descartandoEntradaDaGaveta = true;
      history.back();
    }
    gavetaNoHistorico = false;
  }

  /* A entrada que a gaveta empilhou guarda o hash de quando ela abriu. Voltar
     dela faria o painel restaurar o critério antigo e desfazer o que se mudou
     na gaveta. Este ouvinte roda antes do do painel (movel.js carrega antes):
     engole o popstate e regrava a URL a partir do estado atual. */
  let descartandoEntradaDaGaveta = false;

  function popstateDaGaveta(ev) {
    const aberta = !document.getElementById("gaveta").hidden;
    if (!aberta && !descartandoEntradaDaGaveta) return false;
    ev.stopImmediatePropagation();
    descartandoEntradaDaGaveta = false;
    gavetaNoHistorico = false;
    if (aberta) fecharGaveta(false);
    window.ORCA_painel?.sincronizarUrl?.();
    return true;
  }

  function ligarArrasteDaGaveta() {
    const alca = document.getElementById("gavetaAlca");
    const gaveta = document.getElementById("gaveta");
    let inicioY = null;
    alca.addEventListener("pointerdown", ev => {
      inicioY = ev.clientY;
      alca.setPointerCapture(ev.pointerId);
    });
    alca.addEventListener("pointermove", ev => {
      if (inicioY === null) return;
      const dy = Math.max(0, ev.clientY - inicioY);
      gaveta.style.transform = `translateY(${dy}px)`;
    });
    const soltar = ev => {
      if (inicioY === null) return;
      const dy = ev.clientY - inicioY;
      inicioY = null;
      gaveta.style.transform = "";
      if (dy > 80) fecharGaveta();
    };
    alca.addEventListener("pointerup", soltar);
    alca.addEventListener("pointercancel", soltar);
  }

  // ------------------------------------------------------------ ligações

  function ligar() {
    document.getElementById("abasMovel").addEventListener("click", ev => {
      const botao = ev.target.closest("button[data-vista-movel]");
      if (botao) irPara(botao.dataset.vistaMovel);
    });

    document.getElementById("vistaMais").addEventListener("click", ev => {
      const botao = ev.target.closest("button[data-mais]");
      if (!botao) return;
      if (botao.dataset.mais === "tema") {
        document.getElementById("botaoTema").click();
        return;
      }
      document.body.dataset.subMais = botao.dataset.mais;
      document.getElementById("vistaMais").hidden = true;
      abaDesktop(botao.dataset.mais);
      window.scrollTo(0, 0);
    });

    document.getElementById("barraAjustes").addEventListener("click", abrirGaveta);
    document.getElementById("gavetaFechar").addEventListener("click", () => fecharGaveta());
    document.getElementById("gavetaVeu").addEventListener("click", () => fecharGaveta());
    document.addEventListener("keydown", ev => {
      if (ev.key === "Escape") fecharGaveta();
    });
    ligarArrasteDaGaveta();

    window.addEventListener("popstate", ev => {
      if (popstateDaGaveta(ev)) return;
      if (!MQ.matches) return;
      const v = paramsDoHash(location.hash).params.get("v");
      if (VISTAS.includes(v) && v !== vista) {
        vista = v;
        aplicarVista();
      }
    });

    // O botão de voltar da barra espelha o "Voltar ao estado" do painel.
    const voltarPainel = document.getElementById("botaoVoltar");
    const voltarBarra = document.getElementById("barraVoltar");
    const espelhar = () => {
      voltarBarra.hidden = voltarPainel.hidden;
      document.getElementById("barraMarca").hidden = !voltarPainel.hidden;
    };
    new MutationObserver(espelhar).observe(voltarPainel, { attributes: true, attributeFilter: ["hidden"] });
    espelhar();
    voltarBarra.addEventListener("click", () => voltarPainel.click());

    // Escolher município na busca leva ao mapa, onde o recorte aparece.
    document.getElementById("buscaMunicipioSugestoes").addEventListener("click", () => {
      if (MQ.matches && vista !== "perto") irPara("mapa");
    });

    document.addEventListener("orca:mapa-criado", moverCamadas);

    // `change` do matchMedia nem sempre chega (emulação de tamanho, alguns
    // WebViews); o `resize` cobre o resto. `noCelular` evita entrar duas vezes.
    let noCelular = false;
    const sincronizarModo = () => {
      if (MQ.matches === noCelular) return;
      noCelular = MQ.matches;
      if (noCelular) entrarNoCelular();
      else sairDoCelular();
      window.ORCA_painel?.modoMudou?.();
    };
    MQ.addEventListener("change", sincronizarModo);
    window.addEventListener("resize", sincronizarModo);
    sincronizarModo();
  }

  window.ORCA = Object.assign(window.ORCA || {}, {
    movel: {
      ehCelular: () => MQ.matches,
      irPara,
      vistaAtual: () => vista,
      abrirGaveta,
      fecharGaveta: () => fecharGaveta(),
    },
  });

  ligar();
})();
