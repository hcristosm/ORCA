from pathlib import Path

from src.config import caminho_manifesto_cprm


def test_caminho_manifesto_cprm_usa_uf_minuscula():
    caminho = caminho_manifesto_cprm("SP", Path("/tmp/dados"))
    assert caminho == Path("/tmp/dados/cprm_manifest_sp.json")
