"""Índice nacional leve de setores (`setores_pontos.json`) para a tela "Perto de mim"."""

import json
from pathlib import Path

from typer.testing import CliRunner

from src.cli import app
from src.config import caminho_indice_setores
from src.export.indice_setores import gerar_indice_setores

CAMPOS = [
    "num_setor", "uf", "munic", "grau_risco", "lat", "lon",
    "oeste", "sul", "leste", "norte", "chuva_24h", "chuva_72h",
]


def _quadrado(cx: float, cy: float, lado: float = 0.01) -> dict:
    d = lado / 2
    anel = [[cx - d, cy - d], [cx + d, cy - d], [cx + d, cy + d], [cx - d, cy + d], [cx - d, cy - d]]
    return {"type": "Polygon", "coordinates": [anel]}


def _feicao(num: str, cx: float, cy: float, geometria: dict | None = None) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "num_setor": num, "munic": "CIDADE X", "grau_risco": "Alto",
            "chuva_24h": 1.5, "chuva_72h": 4.25,
        },
        "geometry": _quadrado(cx, cy) if geometria is None else geometria,
    }


def _escrever_uf(dados: Path, uf: str, feicoes: list[dict], referencia: str | None = None) -> None:
    (dados / f"setores_{uf}.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feicoes})
    )
    if referencia is not None:
        (dados / f"meta_{uf}.json").write_text(json.dumps({"referencia": referencia}))


def _ufs(dados: Path, ufs: list[str]) -> None:
    (dados / "ufs_disponiveis.json").write_text(json.dumps(ufs))


def _ler(dados: Path) -> dict:
    return json.loads(caminho_indice_setores(dados).read_text())


def _dados_validos(dados: Path) -> None:
    _escrever_uf(dados, "rj", [_feicao("RJ_1", -42.5, -22.3), _feicao("RJ_2", -42.6, -22.4)])
    _escrever_uf(dados, "sp", [_feicao("SP_1", -46.6, -23.5)])
    _ufs(dados, ["rj", "sp"])


def test_indice_um_registro_por_setor_das_ufs_publicadas(tmp_path: Path):
    _dados_validos(tmp_path)

    total = gerar_indice_setores(tmp_path)

    indice = _ler(tmp_path)
    assert total == 3
    assert len(indice["setores"]) == 3
    assert indice["campos"] == CAMPOS
    assert indice["versao"] == 1


def test_indice_ignora_geojson_de_uf_fora_do_ufs_disponiveis(tmp_path: Path):
    _dados_validos(tmp_path)
    _ufs(tmp_path, ["rj"])

    gerar_indice_setores(tmp_path)

    indice = _ler(tmp_path)
    i_uf = indice["campos"].index("uf")
    assert {linha[i_uf] for linha in indice["setores"]} == {"rj"}


def test_indice_centroide_arredondado_e_caixa_contem_centroide(tmp_path: Path):
    _escrever_uf(tmp_path, "rj", [_feicao("RJ_1", -42.5, -22.3)])
    _ufs(tmp_path, ["rj"])

    gerar_indice_setores(tmp_path)

    indice = _ler(tmp_path)
    registro = dict(zip(indice["campos"], indice["setores"][0], strict=True))
    assert registro["lat"] == -22.3
    assert registro["lon"] == -42.5
    assert registro["oeste"] < registro["lon"] < registro["leste"]
    assert registro["sul"] < registro["lat"] < registro["norte"]
    assert registro["chuva_72h"] == 4.25
    assert registro["munic"] == "CIDADE X"


def test_indice_feicao_sem_geometria_e_pulada(tmp_path: Path):
    _escrever_uf(tmp_path, "rj", [_feicao("RJ_1", -42.5, -22.3), {**_feicao("RJ_2", 0, 0), "geometry": None}])
    _ufs(tmp_path, ["rj"])

    assert gerar_indice_setores(tmp_path) == 1


def test_indice_geojson_ilegivel_pula_a_uf(tmp_path: Path):
    _dados_validos(tmp_path)
    (tmp_path / "setores_sp.geojson").write_text("{")

    assert gerar_indice_setores(tmp_path) == 2


def test_indice_sem_ufs_disponiveis_devolve_none_e_nao_grava(tmp_path: Path):
    _escrever_uf(tmp_path, "rj", [_feicao("RJ_1", -42.5, -22.3)])

    assert gerar_indice_setores(tmp_path) is None
    assert not caminho_indice_setores(tmp_path).exists()


def test_indice_referencia_por_uf_vem_do_meta(tmp_path: Path):
    _escrever_uf(tmp_path, "rj", [_feicao("RJ_1", -42.5, -22.3)], referencia="2026-11-07T15:00:00+00:00")
    _escrever_uf(tmp_path, "sp", [_feicao("SP_1", -46.6, -23.5)])
    _ufs(tmp_path, ["rj", "sp"])

    gerar_indice_setores(tmp_path)

    assert _ler(tmp_path)["referencia_por_uf"] == {"rj": "2026-11-07T15:00:00+00:00"}


def test_cli_indexar_setores(tmp_path: Path):
    runner = CliRunner()
    _dados_validos(tmp_path)

    resultado = runner.invoke(app, ["indexar-setores", "--dados", str(tmp_path)])
    assert resultado.exit_code == 0, resultado.output
    assert "Índice de setores: 3 setores de 2 UF(s)." in resultado.output

    vazio = tmp_path / "vazio"
    vazio.mkdir()
    resultado = runner.invoke(app, ["indexar-setores", "--dados", str(vazio)])
    assert resultado.exit_code == 1
