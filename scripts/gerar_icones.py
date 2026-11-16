"""Gera os ícones do app e o logo do README a partir de uma arte quadrada.

Uso (precisa de Pillow, que não é dependência do projeto):

    pip install pillow
    python scripts/gerar_icones.py caminho/da/arte.png

A arte de origem é a orca sobre fundo azul, com cantos arredondados já
desenhados (o que sobra nos cantos é descartado e preenchido com o azul).
Saídas:

- docs/dashboard/icons/orca-{32,192,512}.png: quadrado arredondado com cantos
  transparentes (favicon, cabeçalho, ícone "any" do manifesto);
- docs/dashboard/icons/orca-maskable-{192,512}.png: fundo azul até a borda e a
  orca reduzida para caber no círculo seguro (80%) que o Android recorta;
- docs/dashboard/icons/orca-apple-180.png: fundo azul até a borda, sem
  transparência (o iOS arredonda sozinho);
- docs/logo/orca-logo.png: o cartão azul com "ORCA" escrito embaixo, para o
  README. Serve nos temas claro e escuro, então é um arquivo só.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
ICONES = RAIZ / "docs" / "dashboard" / "icons"
LOGO = RAIZ / "docs" / "logo"
FONTE = RAIZ / "docs" / "dashboard" / "fonts" / "plex-cond-700.woff2"

AZUL = (6, 84, 133)  # #065485, mediana do fundo da arte
TINTA = (238, 238, 234)  # branco da barriga da orca
LADO = 1024  # resolução de trabalho
RAIO_CANTO = 0.225  # proporção do raio do quadrado arredondado
ZONA_SEGURA = 0.78  # escala da arte no ícone maskable (círculo seguro = 80%)


def _fundo_cheio(origem: Image.Image) -> Image.Image:
    """Arte em LADO x LADO com os cantos refeitos em azul liso."""
    arte = origem.convert("RGB").resize((LADO, LADO), Image.Resampling.LANCZOS)
    # Máscara com raio maior que o da arte: tudo que fica dentro dela é fundo
    # azul ou orca, nunca o preto dos cantos.
    mascara = Image.new("L", (LADO, LADO), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        (0, 0, LADO - 1, LADO - 1), radius=int(LADO * 0.2), fill=255
    )
    base = Image.new("RGB", (LADO, LADO), AZUL)
    base.paste(arte, (0, 0), mascara)
    return base


def _reduzida(base: Image.Image, escala: float) -> Image.Image:
    lado = int(LADO * escala)
    menor = base.resize((lado, lado), Image.Resampling.LANCZOS)
    saida = Image.new("RGB", (LADO, LADO), AZUL)
    deslocamento = (LADO - lado) // 2
    saida.paste(menor, (deslocamento, deslocamento))
    return saida


def _arredondada(imagem: Image.Image) -> Image.Image:
    """Recorta em quadrado arredondado, com cantos transparentes (4x supersample)."""
    grande = LADO * 4
    mascara = Image.new("L", (grande, grande), 0)
    ImageDraw.Draw(mascara).rounded_rectangle(
        (0, 0, grande - 1, grande - 1), radius=int(grande * RAIO_CANTO), fill=255
    )
    saida = imagem.convert("RGBA")
    saida.putalpha(mascara.resize((LADO, LADO), Image.Resampling.LANCZOS))
    return saida


def _com_nome(base: Image.Image) -> Image.Image:
    """Cartão com a orca em cima e "ORCA" embaixo."""
    cartao = Image.new("RGB", (LADO, LADO), AZUL)
    # Caixa da orca: tudo que se afasta do azul do fundo.
    diferenca = ImageChops.difference(base, Image.new("RGB", base.size, AZUL)).convert("L")
    caixa = diferenca.point(lambda v: 255 if v > 30 else 0).getbbox() or (0, 0, LADO, LADO)
    orca = base.crop(caixa)
    largura = int(LADO * 0.76)
    altura = int(orca.height * largura / orca.width)
    orca = orca.resize((largura, altura), Image.Resampling.LANCZOS)

    fonte = ImageFont.truetype(str(FONTE), int(LADO * 0.19))
    desenho = ImageDraw.Draw(cartao)
    texto = "ORCA"
    t0, t1, t2, t3 = desenho.textbbox((0, 0), texto, font=fonte)
    altura_texto = t3 - t1
    vao = int(LADO * 0.07)
    topo = (LADO - (altura + vao + altura_texto)) // 2

    cartao.paste(orca, ((LADO - largura) // 2, topo))
    desenho.text(
        ((LADO - (t2 - t0)) // 2 - t0, topo + altura + vao - t1), texto, font=fonte, fill=TINTA
    )
    return _arredondada(cartao)


def _salvar(imagem: Image.Image, lado: int, destino: Path) -> None:
    imagem.resize((lado, lado), Image.Resampling.LANCZOS).save(destino, optimize=True)
    print(f"{destino.relative_to(RAIZ)} ({lado}x{lado})")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    base = _fundo_cheio(Image.open(argv[1]))
    arredondada = _arredondada(base)
    for lado in (32, 192, 512):
        _salvar(arredondada, lado, ICONES / f"orca-{lado}.png")
    maskable = _reduzida(base, ZONA_SEGURA)
    for lado in (192, 512):
        _salvar(maskable, lado, ICONES / f"orca-maskable-{lado}.png")
    _salvar(base, 180, ICONES / "orca-apple-180.png")
    _salvar(_com_nome(base), 640, LOGO / "orca-logo.png")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
