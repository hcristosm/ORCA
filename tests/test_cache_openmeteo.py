from pathlib import Path

import pytest

from src.storage_cache_openmeteo import CacheOpenMeteo


def test_horas_faltantes_cache_vazio_retorna_tudo(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00", "2026-08-10T01:00"])
    assert faltando == {(-23.5, -46.6): ["2026-08-10T00:00", "2026-08-10T01:00"]}


def test_gravar_depois_horas_faltantes_reflete_o_que_foi_gravado(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.2)], "chuva_mm", "2026-08-10T05:00")

    faltando = cache.horas_faltantes([ponto], "chuva_mm", ["2026-08-10T00:00", "2026-08-10T01:00"])

    assert faltando == {ponto: ["2026-08-10T01:00"]}


def test_gravar_e_ler_preserva_valor_null(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", None)], "chuva_mm", "2026-08-10T05:00")

    lido = cache.ler([ponto], "chuva_mm", ["2026-08-10T00:00"])

    assert lido == {ponto: {"2026-08-10T00:00": None}}


def test_gravar_upsert_sobrescreve_valor_existente(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")
    cache.gravar([(ponto, "2026-08-10T00:00", 2.0)], "chuva_mm", "2026-08-10T06:00")

    lido = cache.ler([ponto], "chuva_mm", ["2026-08-10T00:00"])

    assert lido == {ponto: {"2026-08-10T00:00": 2.0}}


def test_variaveis_diferentes_nao_se_confundem(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    ponto = (-23.5, -46.6)
    cache.gravar([(ponto, "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    faltando_vento = cache.horas_faltantes([ponto], "vento_rajada_kmh", ["2026-08-10T00:00"])

    assert faltando_vento == {ponto: ["2026-08-10T00:00"]}


def test_pontos_proximos_arredondam_para_a_mesma_chave(tmp_path: Path):
    cache = CacheOpenMeteo(tmp_path / "cache.sqlite")
    cache.gravar([((-23.50001, -46.60001), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00"])

    assert faltando == {}


def test_arquivo_corrompido_degrada_para_cache_vazio(tmp_path: Path, caplog):
    caminho = tmp_path / "cache.sqlite"
    caminho.write_bytes(b"nao e um sqlite valido")

    cache = CacheOpenMeteo(caminho)
    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00"])
    cache.gravar([((-23.5, -46.6), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    assert faltando == {(-23.5, -46.6): ["2026-08-10T00:00"]}
    # Verify that a warning was logged when opening the corrupted file
    assert any("Falha ao abrir cache Open-Meteo" in record.message for record in caplog.records)


def test_diretorio_pai_e_criado_automaticamente(tmp_path: Path):
    caminho = tmp_path / "subdir" / "cache.sqlite"
    cache = CacheOpenMeteo(caminho)
    cache.gravar([((-23.5, -46.6), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")
    assert caminho.exists()


def test_caminho_invalido_mkdir_error_degrada_para_cache_vazio(tmp_path: Path, caplog):
    # Create a file where a directory is expected, so mkdir will fail with NotADirectoryError (OSError)
    bloqueador = tmp_path / "bloqueador"
    bloqueador.write_text("arquivo em lugar de diretorio")

    caminho = bloqueador / "cache.sqlite"

    # Should not raise - should degrade to empty cache with warning
    cache = CacheOpenMeteo(caminho)
    faltando = cache.horas_faltantes([(-23.5, -46.6)], "chuva_mm", ["2026-08-10T00:00"])
    cache.gravar([((-23.5, -46.6), "2026-08-10T00:00", 1.0)], "chuva_mm", "2026-08-10T05:00")

    # Should behave as empty cache
    assert faltando == {(-23.5, -46.6): ["2026-08-10T00:00"]}
    # Verify that a warning was logged for the OSError
    assert any("Falha ao abrir cache Open-Meteo" in record.message for record in caplog.records)
