"""Roda `tests/js/calculo.html` num navegador de verdade, dentro do pytest.

Os cálculos do front-end (grau de risco, fonte, sobreposição, proximidade,
índice de setores, cobertura por município) vivem em `docs/dashboard/calculo.js`
e `comum.js`, e os casos estão numa página HTML porque o projeto não usa Node.
Até aqui essa página só rodava quando alguém lembrava de abrir o navegador, e
um gate que depende de memória não é gate: a regra da casa é não julgar nada
pelo que se supõe que rodou.

Entrar pelo `pytest`, e não por um passo próprio no CI, é de propósito: o CI já
roda `pytest`, então não há workflow novo para manter. O navegador é o Chrome
do sistema (`channel="chrome"`), que a imagem do runner do GitHub já traz, sem
baixar browser nenhum.

Fora do CI, sem playwright ou sem navegador, o teste é pulado com o motivo. No
CI ele falha, porque lá pular em silêncio seria o mesmo que não ter o teste.
"""

from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
PAGINA = "tests/js/calculo.html"

# Ruído do navegador, não da página: o aviso de `frame-ancestors` num <meta>, e
# a linha genérica de recurso que não carregou, que vem sem URL. Recurso
# faltando é pego pelo listener de `response`, que diz QUAL, e o listener de
# console fica só com erro de JavaScript.
RUIDO_DE_CONSOLE = ("frame-ancestors", "Failed to load resource")

NO_CI = os.environ.get("CI") == "true"


def _pular_ou_falhar(motivo: str):
    if NO_CI:
        pytest.fail(f"{motivo} (no CI isto não pode ser pulado)")
    pytest.skip(motivo)


def _servidor():
    """Serve a raiz do repositório numa porta livre, como manda o CONTRIBUTING.

    `fetch()` e `document.write` de script relativo funcionam por `file://` só
    com flag de navegador que afrouxa a origem; servir por HTTP é o que o
    dashboard de verdade faz.
    """
    class Silencioso(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            # Uma linha por requisição poluiria a saída do pytest.
            pass

    handler = partial(Silencioso, directory=str(RAIZ))
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def test_calculos_do_front_end_passam_no_navegador():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _pular_ou_falhar("playwright não instalado: pip install -e '.[dev]'")

    servidor = _servidor()
    porta = servidor.server_address[1]
    try:
        with sync_playwright() as p:
            try:
                navegador = p.chromium.launch(channel="chrome")
            except Exception as exc:  # noqa: BLE001 - qualquer falha aqui é "sem navegador"
                _pular_ou_falhar(f"sem Chrome para rodar os casos de JS: {exc}")

            pagina = navegador.new_page()
            erros: list[str] = []
            pagina.on(
                "console",
                lambda m: m.type == "error"
                and not any(r in m.text for r in RUIDO_DE_CONSOLE)
                and erros.append(m.text),
            )
            pagina.on("pageerror", lambda e: erros.append(str(e)))
            # O favicon é pedido pelo navegador, não pela página: a ausência
            # dele numa página de teste não é defeito de nada.
            pagina.on(
                "response",
                lambda r: r.status >= 400
                and not r.url.endswith("/favicon.ico")
                and erros.append(f"HTTP {r.status} em {r.url}"),
            )
            try:
                pagina.goto(f"http://127.0.0.1:{porta}/{PAGINA}")
                pagina.wait_for_function(
                    "/PASSOU|FALHOU/.test(document.body.innerText)", timeout=30_000
                )
                resultado = pagina.inner_text("#resultado")
                falhas = pagina.eval_on_selector_all(
                    "li.falha", "nos => nos.map(n => n.textContent)"
                )
            finally:
                navegador.close()
    finally:
        servidor.shutdown()

    assert not falhas, "casos de JS falharam:\n" + "\n".join(falhas)
    assert resultado.startswith("PASSOU"), resultado
    assert not erros, "console do navegador sujo:\n" + "\n".join(erros)
