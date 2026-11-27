"""Download dos setores do BELUGA, com a rede mockada.

Um caso por modo de falha, e em todos eles a regra é a mesma: o comando sai
com 1 e a UF fica com o GeoPackage anterior, intacto. `responses.activate`
garante que nenhum teste bate na rede de verdade: requisição não registrada
levanta ConnectionError.
"""

import hashlib
import json
import sqlite3
from pathlib import Path

import geopandas as gpd
import pytest
import responses
from shapely.geometry import Polygon
from typer.testing import CliRunner

from src.cli import app
from src.config import (
    CAMADA_SETORES,
    UFS_VALIDAS,
    caminho_manifesto_beluga,
    caminho_setores_beluga,
)
from src.ingest.beluga import (
    URL_BASE,
    BelugaFetchError,
    baixar_manifest,
    contagens_publicadas,
)
from src.storage import ler_setores, salvar_setores

runner = CliRunner()

URL_MANIFEST = f"{URL_BASE}manifest.json"
URL_SP = f"{URL_BASE}setores_sp.geojson"

FONTES = [
    {
        "id": "br-sgb-setorizacao",
        "nome": "Setorização de Risco Geológico (CPRM/SGB)",
        "orgao": "Serviço Geológico do Brasil (SGB/CPRM)",
        "licenca": {"nome": "não declarada no serviço", "url": None},
        "publicada": True,
    },
    {
        "id": "sp-suzano-defesa-civil",
        "nome": "Setorização de Suzano",
        "orgao": "Defesa Civil de Suzano",
        "licenca": {"nome": "CC-BY-4.0", "url": None},
        "publicada": True,
    },
]


def _geojson(quantidade: int) -> str:
    feicoes = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-46.61, -23.51], [-46.59, -23.51], [-46.59, -23.49], [-46.61, -23.51],
                ]],
            },
            "properties": {
                "num_setor": f"SP_CIDADEX_SR_{i}_CPRM",
                "uf": "SP",
                "munic": "CIDADE X",
                "grau_risco": "Alto",
                "data_setor": "2026-10-01",
                "orgao_exec": "SGB",
                "bl_fonte": "br-sgb-setorizacao",
                "bl_produto": "setorizacao_risco",
                "bl_licenca": "não declarada no serviço",
                "bl_sob_cp": None,
                "bl_cp_frac": None,
            },
        }
        for i in range(quantidade)
    ]
    return json.dumps({"type": "FeatureCollection", "features": feicoes})


def _manifest(
    corpo_sp: str,
    contrato: str = "v1",
    setores: int | None = None,
    sha256: str | None = None,
    sp_no_manifest: bool = True,
) -> dict:
    """Manifest com as 27 UFs; só a de SP é consultada pelos testes."""
    ufs = {
        uf.lower(): {
            "arquivo": f"setores_{uf.lower()}.geojson",
            "setores": 1,
            "bytes": 1,
            "sha256": "0" * 64,
            "por_fonte": {"br-sgb-setorizacao": 1},
        }
        for uf in sorted(UFS_VALIDAS)
        if uf != "SP"
    }
    entrada_sp = {
        "arquivo": "setores_sp.geojson",
        "setores": setores if setores is not None else len(json.loads(corpo_sp)["features"]),
        "bytes": len(corpo_sp),
        "sha256": sha256 if sha256 is not None else hashlib.sha256(corpo_sp.encode()).hexdigest(),
        "por_fonte": {"br-sgb-setorizacao": 2, "sp-suzano-defesa-civil": 3},
    }
    # Mantém 27 entradas mesmo sem SP: é o caso "o manifest conta 27, mas a UF
    # que eu quero não está lá" (chave renomeada do lado do BELUGA), que é
    # diferente de publicação parcial e tem mensagem própria.
    ufs["sp" if sp_no_manifest else "zz"] = entrada_sp
    return {
        "contrato": contrato,
        "versao_esquema": "1.1.0",
        "gerado_em": "2026-11-27T03:03:37+00:00",
        "crs": "EPSG:4326",
        "ufs": ufs,
        "fontes": FONTES,
    }


@pytest.fixture
def anterior(tmp_path: Path) -> Path:
    """Semeia o `beluga_sp.gpkg` da coleta anterior, com um setor reconhecível."""
    gdf = gpd.GeoDataFrame(
        {"num_setor": ["SP_ANTIGO_1"], "munic": ["CIDADE X"], "grau_risco": ["Alto"]},
        geometry=[Polygon([(-46.61, -23.51), (-46.59, -23.51), (-46.59, -23.49)])],
        crs="EPSG:4326",
    )
    caminho = caminho_setores_beluga("SP", tmp_path)
    salvar_setores(gdf, caminho)
    return caminho


def _invocar(tmp_path: Path, publicado: Path | None = None):
    comando = ["baixar-beluga", "--ufs", "SP", "--diretorio", str(tmp_path)]
    if publicado is not None:
        comando += ["--publicado", str(publicado)]
    return runner.invoke(app, comando)


def _intacto(caminho: Path) -> None:
    assert list(ler_setores(caminho)["num_setor"]) == ["SP_ANTIGO_1"], (
        "a UF que falhou não ficou com o dado anterior"
    )


@responses.activate
def test_baixa_uf_e_grava_gpkg_e_manifesto(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(responses.GET, URL_MANIFEST, json=_manifest(corpo), status=200)
    responses.add(responses.GET, URL_SP, body=corpo, status=200)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 0, resultado.output
    assert "1/1 UF(s) baixada(s) do BELUGA, 2 setores" in resultado.output
    gravado = ler_setores(caminho_setores_beluga("SP", tmp_path))
    assert len(gravado) == 2
    assert gravado["bl_fonte"].iloc[0] == "br-sgb-setorizacao"
    manifesto = json.loads(caminho_manifesto_beluga(tmp_path).read_text())
    assert manifesto["contrato"] == "v1"


def test_contagens_publicadas_le_o_total_de_cada_meta(tmp_path: Path):
    (tmp_path / "meta_sp.json").write_text(json.dumps({"total_setores": 907}))
    (tmp_path / "meta_rj.json").write_text(json.dumps({"total_setores": 346}))

    assert contagens_publicadas(tmp_path) == {"SP": 907, "RJ": 346}


def test_contagens_publicadas_sem_diretorio_nao_levanta(tmp_path: Path):
    # É o estado quando a busca do gh-pages falha. UF sem piso é pior que UF
    # com piso, mas travar as 27 por isso seria pior ainda: quem barra o
    # conjunto é a guarda de publicação.
    assert contagens_publicadas(tmp_path / "nao-existe") == {}


def test_contagens_publicadas_ignora_meta_ilegivel_e_total_que_nao_e_inteiro(tmp_path: Path):
    (tmp_path / "meta_sp.json").write_text(json.dumps({"total_setores": 907}))
    (tmp_path / "meta_rj.json").write_text("{isto não é json")
    (tmp_path / "meta_mg.json").write_text(json.dumps({"total_setores": "3695"}))
    (tmp_path / "meta_ba.json").write_text(json.dumps({"total_setores": True}))
    (tmp_path / "meta_pe.json").write_text(json.dumps({}))

    # Só SP ganha piso; as outras ficam sem, e sem piso é diferente de piso 0:
    # piso 0 aceitaria qualquer coisa, inclusive publicação vazia.
    assert contagens_publicadas(tmp_path) == {"SP": 907}


@responses.activate
def test_sob_cp_fica_booleano_no_gpkg_e_nao_texto(tmp_path: Path, anterior: Path):
    # Em JavaScript `"False"` é verdadeiro. Se `bl_sob_cp` virar texto no
    # GeoPackage, o `to_file(driver="GeoJSON")` do dashboard repassa a string e
    # o filtro de sobreposição marca TODO setor externo como repetido, sem
    # erro nenhum no caminho. Confere o tipo DECLARADO no arquivo, não o que o
    # pandas devolve: coluna TEXT lida pelo pandas também vira `object`.
    colecao = json.loads(_geojson(3))
    for feicao, valor in zip(colecao["features"], [True, False, None]):
        feicao["properties"]["bl_sob_cp"] = valor
    corpo = json.dumps(colecao)
    responses.add(responses.GET, URL_MANIFEST, json=_manifest(corpo, setores=3), status=200)
    responses.add(responses.GET, URL_SP, body=corpo, status=200)

    assert _invocar(tmp_path).exit_code == 0

    with sqlite3.connect(caminho_setores_beluga("SP", tmp_path)) as conexao:
        ddl = conexao.execute(
            "select sql from sqlite_master where name = ?", (CAMADA_SETORES,)
        ).fetchone()[0]
        assert '"bl_sob_cp" BOOLEAN' in ddl, ddl
        tipos = dict(
            conexao.execute(
                f"select typeof(bl_sob_cp), count(*) from {CAMADA_SETORES} group by 1"
            ).fetchall()
        )
    assert tipos == {"integer": 2, "null": 1}, tipos


@responses.activate
def test_manifest_ausente_falha_e_preserva_o_dado_anterior(tmp_path: Path, anterior: Path):
    responses.add(responses.GET, URL_MANIFEST, status=404)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "FALHA no manifest do BELUGA" in resultado.output
    _intacto(anterior)


@responses.activate
def test_contrato_diferente_de_v1_e_recusado(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(
        responses.GET, URL_MANIFEST, json=_manifest(corpo, contrato="v2"), status=200
    )
    responses.add(responses.GET, URL_SP, body=corpo, status=200)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "'v2'" in resultado.output
    _intacto(anterior)
    # Contrato errado para ANTES de pedir qualquer GeoJSON.
    assert [c.request.url for c in responses.calls] == [URL_MANIFEST]


@responses.activate
def test_manifest_sem_as_27_ufs_e_recusado(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    manifest = _manifest(corpo)
    del manifest["ufs"]["ba"]
    responses.add(responses.GET, URL_MANIFEST, json=manifest, status=200)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "26 UF(s)" in resultado.output
    _intacto(anterior)


@responses.activate
def test_sha256_que_nao_bate_descarta_o_arquivo(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(
        responses.GET, URL_MANIFEST, json=_manifest(corpo, sha256="f" * 64), status=200
    )
    responses.add(responses.GET, URL_SP, body=corpo, status=200)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "sha256" in resultado.output
    _intacto(anterior)


@responses.activate
def test_geojson_truncado_e_recusado_pela_contagem_de_feicoes(tmp_path: Path, anterior: Path):
    # Arquivo íntegro para o sha256 (o BELUGA pode ter publicado um GeoJSON
    # curto e o sha256 do próprio arquivo curto), mas com menos feições que o
    # manifest declara: é a defesa que tem mensagem própria.
    corpo = _geojson(2)
    responses.add(responses.GET, URL_MANIFEST, json=_manifest(corpo, setores=7), status=200)
    responses.add(responses.GET, URL_SP, body=corpo, status=200)

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "truncado" in resultado.output
    _intacto(anterior)


@responses.activate
def test_uf_faltando_no_manifest_falha_sem_baixar(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(
        responses.GET, URL_MANIFEST, json=_manifest(corpo, sp_no_manifest=False), status=200
    )

    resultado = _invocar(tmp_path)

    assert resultado.exit_code == 1
    assert "não está no manifest" in resultado.output
    _intacto(anterior)


@responses.activate
def test_publicacao_menor_que_a_anterior_e_recusada(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(responses.GET, URL_MANIFEST, json=_manifest(corpo), status=200)
    responses.add(responses.GET, URL_SP, body=corpo, status=200)
    publicado = tmp_path / "publicado"
    publicado.mkdir()
    (publicado / "meta_sp.json").write_text(json.dumps({"total_setores": 5}))

    resultado = _invocar(tmp_path, publicado=publicado)

    assert resultado.exit_code == 1
    assert "menos que os 5 já" in resultado.output
    _intacto(anterior)


@responses.activate
def test_publicacao_do_mesmo_tamanho_passa_pelo_piso(tmp_path: Path, anterior: Path):
    corpo = _geojson(2)
    responses.add(responses.GET, URL_MANIFEST, json=_manifest(corpo), status=200)
    responses.add(responses.GET, URL_SP, body=corpo, status=200)
    publicado = tmp_path / "publicado"
    publicado.mkdir()
    (publicado / "meta_sp.json").write_text(json.dumps({"total_setores": 2}))

    resultado = _invocar(tmp_path, publicado=publicado)

    assert resultado.exit_code == 0, resultado.output
    assert len(ler_setores(caminho_setores_beluga("SP", tmp_path))) == 2


@responses.activate
def test_manifest_que_nao_e_json_e_recusado():
    responses.add(responses.GET, URL_MANIFEST, body="<html>502</html>", status=200)

    with pytest.raises(BelugaFetchError, match="não é JSON válido"):
        baixar_manifest()
