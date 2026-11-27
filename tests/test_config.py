from pathlib import Path

from src.config import caminho_manifesto_beluga, caminho_setores_beluga


def test_caminho_setores_beluga_usa_uf_minuscula_e_prefixo_proprio():
    # Prefixo `beluga_`, não `risco_`: exigência do contrato de dados do
    # BELUGA, para um GeoPackage antigo da ingestão direta da CPRM/SGB não ser
    # lido como se fosse o novo.
    caminho = caminho_setores_beluga("SP", Path("/tmp/dados"))
    assert caminho == Path("/tmp/dados/beluga_sp.gpkg")


def test_caminho_manifesto_beluga_e_nacional():
    assert caminho_manifesto_beluga(Path("/tmp/dados")) == Path("/tmp/dados/beluga_manifest.json")
