"""Guarda anti-regressão compartilhada pelos dois workflows de publicação.

Invariante da spec: nenhuma publicação destrói dado bom. Os dois deploys
sobrescrevem a branch de destino, então publicar um conjunto vazio -- ou
menor do que o que já está lá -- apaga dado bom. Foi assim que os runs #23 e
#29 destruíram o dashboard, ambos fechando como `success`.

Publicação PARCIAL é aceitável (20 UFs frescas valem mais que nenhuma);
publicar MENOS do que já está no ar, não. Na dúvida (contagem anterior
indisponível ou ilegível), recusa.

Duas propriedades que não podem ser quebradas por nenhuma refatoração:

1. Toda recusa GRAVA `publicar=false` no `$GITHUB_OUTPUT` **antes** de sair
   com 1, nessa ordem. É o output que faz o passo de publicação ser pulado;
   se a falha viesse antes da escrita, a publicação não seria pulada.
2. Toda recusa SAI COM 1. Uma guarda que recusasse em silêncio num cron
   diário poderia bloquear a publicação por semanas sem ninguém notar --
   degradação silenciosa é justamente a doença que estes workflows existem
   para curar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def contar_json(caminho: Path) -> int | None:
    """Conta os itens de um arquivo JSON que deve conter uma lista.

    Devolve `None` -- e não 0 -- para ausente, ilegível ou não-lista: 0
    significa "não há nada publicado, pode publicar à vontade", e tratar um
    estado indeterminado como 0 deixaria passar um conjunto de 1 UF por cima
    do que quer que esteja no ar.
    """
    try:
        dados = json.loads(caminho.read_text())
    except (OSError, ValueError):
        return None
    return len(dados) if isinstance(dados, list) else None


def _inteiro(valor: str | None) -> int | None:
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _gravar_saida(publicar: bool) -> None:
    caminho = os.environ.get("GITHUB_OUTPUT")
    if caminho:
        with open(caminho, "a") as fh:
            fh.write(f"publicar={'true' if publicar else 'false'}\n")


def _recusar(mensagem: str) -> int:
    """Grava `publicar=false` e SÓ ENTÃO devolve 1. A ordem é a garantia."""
    print(f"::error::{mensagem}")
    _gravar_saida(False)
    return 1


def conferir(atual: int | None, anterior: int | None, rotulo: str) -> int:
    if anterior is None:
        return _recusar(
            "Contagem anterior indisponível ou inválida. Sem ela não dá para "
            "confirmar que não estamos regredindo -- publicação recusada."
        )
    if atual is None:
        return _recusar(
            f"Esta execução não gerou um conjunto legível de {rotulo} "
            f"(anterior={anterior}). Publicação recusada para não apagar o que está no ar."
        )

    print(f"{rotulo} nesta execução: {atual} (anterior: {anterior}).")

    if atual == 0:
        return _recusar(
            f"Conjunto atual está vazio (atual=0, anterior={anterior}). "
            "Publicação recusada para não apagar o que está no ar."
        )
    if atual < anterior:
        return _recusar(
            f"Regressão detectada: atual={atual} é menor que anterior={anterior}. "
            "Publicação recusada."
        )

    _gravar_saida(True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atual", help="Contagem desta execução (inteiro).")
    parser.add_argument("--atual-json", type=Path, help="Arquivo JSON (lista) a contar como atual.")
    parser.add_argument("--anterior", help="Contagem já publicada (inteiro).")
    parser.add_argument(
        "--anterior-json", type=Path, help="Arquivo JSON (lista) a contar como anterior."
    )
    parser.add_argument("--rotulo", default="itens", help="Nome do que se conta, para as mensagens.")
    args = parser.parse_args(argv)

    atual = contar_json(args.atual_json) if args.atual_json else _inteiro(args.atual)
    anterior = contar_json(args.anterior_json) if args.anterior_json else _inteiro(args.anterior)
    return conferir(atual, anterior, args.rotulo)


if __name__ == "__main__":
    sys.exit(main())
