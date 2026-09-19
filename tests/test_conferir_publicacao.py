"""Testes da guarda anti-regressão compartilhada (scripts/conferir_publicacao.py).

O que estes testes protegem não é o cálculo (trivial), e sim as duas
propriedades que os runs #23 e #29 ensinaram: toda recusa grava
`publicar=false` ANTES de sinalizar falha, e toda recusa sinaliza falha.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.conferir_publicacao import contar_json, main


@pytest.fixture
def saida(tmp_path, monkeypatch) -> Path:
    caminho = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(caminho))
    return caminho


def _publicar(saida: Path) -> str | None:
    if not saida.exists():
        return None
    for linha in saida.read_text().splitlines():
        if linha.startswith("publicar="):
            return linha.split("=", 1)[1]
    return None


def test_aprova_quando_atual_maior_ou_igual(saida):
    assert main(["--atual", "27", "--anterior", "27"]) == 0
    assert _publicar(saida) == "true"


def test_aprova_publicacao_parcial_acima_do_anterior(saida):
    assert main(["--atual", "20", "--anterior", "18"]) == 0
    assert _publicar(saida) == "true"


def test_recusa_regressao(saida):
    assert main(["--atual", "1", "--anterior", "27"]) == 1
    assert _publicar(saida) == "false"


def test_recusa_conjunto_vazio(saida):
    assert main(["--atual", "0", "--anterior", "0"]) == 1
    assert _publicar(saida) == "false"


def test_recusa_quando_anterior_indisponivel(saida):
    assert main(["--atual", "27", "--anterior", ""]) == 1
    assert _publicar(saida) == "false"


def test_recusa_quando_anterior_nao_e_inteiro(saida):
    assert main(["--atual", "27", "--anterior", "vinte"]) == 1
    assert _publicar(saida) == "false"


def test_recusa_quando_atual_indisponivel(saida):
    assert main(["--atual", "", "--anterior", "27"]) == 1
    assert _publicar(saida) == "false"


def test_conta_listas_json(tmp_path, saida):
    atual = tmp_path / "atual.json"
    atual.write_text(json.dumps(["sp", "rj", "mg"]))
    anterior = tmp_path / "anterior.json"
    anterior.write_text(json.dumps(["sp", "rj"]))
    assert main(["--atual-json", str(atual), "--anterior-json", str(anterior)]) == 0
    assert _publicar(saida) == "true"


def test_json_ausente_recusa_em_vez_de_contar_zero(tmp_path, saida):
    """Ausente é indeterminado, não zero: zero autorizaria sobrescrever no escuro."""
    assert contar_json(tmp_path / "nao_existe.json") is None
    assert main(["--atual", "1", "--anterior-json", str(tmp_path / "nao_existe.json")]) == 1
    assert _publicar(saida) == "false"


def test_json_ilegivel_recusa(tmp_path, saida):
    quebrado = tmp_path / "quebrado.json"
    quebrado.write_text("{isto não é json")
    assert contar_json(quebrado) is None
    assert main(["--atual-json", str(quebrado), "--anterior", "5"]) == 1
    assert _publicar(saida) == "false"


def test_json_que_nao_e_lista_recusa(tmp_path, saida):
    objeto = tmp_path / "objeto.json"
    objeto.write_text(json.dumps({"sp": 1}))
    assert contar_json(objeto) is None
    assert main(["--atual-json", str(objeto), "--anterior", "5"]) == 1
    assert _publicar(saida) == "false"


def test_recusa_grava_saida_antes_de_falhar(saida):
    """A ordem é o ponto: é o output que pula a publicação, não o exit code."""
    codigo = main(["--atual", "1", "--anterior", "27"])
    assert _publicar(saida) == "false", "output precisa existir mesmo com a recusa"
    assert codigo == 1, "a recusa precisa ser visível como falha do run"


def test_sem_github_output_nao_quebra(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert main(["--atual", "27", "--anterior", "27"]) == 0
