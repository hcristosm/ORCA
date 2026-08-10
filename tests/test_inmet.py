import io
import zipfile
from pathlib import Path

import pytest
import responses

from src.ingest.inmet import (
    ESTACOES_URL,
    INMETFetchError,
    _carregar_manifesto,
    _crc32_estacao,
    _parse_csv_estacao,
    _salvar_manifesto,
    baixar_zip_ano_condicional,
    fetch_estacoes,
    ler_serie_estacao,
)

CSV_ESTACAO_EXEMPLO = (
    "REGIAO:;SE\r\n"
    "UF:;SP\r\n"
    "ESTACAO:;SAO PAULO - MIRANTE\r\n"
    "CODIGO (WMO):;A701\r\n"
    "LATITUDE:;-23,4962888\r\n"
    "LONGITUDE:;-46,6200666\r\n"
    "ALTITUDE:;785,64\r\n"
    "DATA DE FUNDACAO:;25/07/06\r\n"
    "Data;Hora UTC;PRECIPITACAO TOTAL, HORARIO (mm);OUTRA COLUNA\r\n"
    "2026/01/01;0000 UTC;0;924,7\r\n"
    "2026/01/01;0100 UTC;2,4;925,1\r\n"
    "2026/01/01;0200 UTC;;925,1\r\n"
).encode("latin-1")


def _zip_com_estacao(tmp_path: Path, nome_arquivo: str, conteudo: bytes) -> Path:
    zip_path = tmp_path / "inmet_2026.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(nome_arquivo, conteudo)
    return zip_path


def test_parse_csv_estacao_le_datas_e_chuva():
    df = _parse_csv_estacao(CSV_ESTACAO_EXEMPLO)

    assert len(df) == 3
    assert df["chuva_mm"].iloc[0] == 0.0
    assert df["chuva_mm"].iloc[1] == 2.4
    assert df.index[0].hour == 0
    assert df.index[1].hour == 1


def test_parse_csv_estacao_trata_valor_ausente_como_nan():
    df = _parse_csv_estacao(CSV_ESTACAO_EXEMPLO)

    assert df["chuva_mm"].isna().iloc[2]


def test_ler_serie_estacao_encontra_arquivo_por_uf_e_codigo(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    serie = ler_serie_estacao(zip_path, "SP", "A701")

    assert len(serie) == 3


def test_ler_serie_estacao_levanta_erro_se_estacao_nao_existe(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    with pytest.raises(INMETFetchError):
        ler_serie_estacao(zip_path, "SP", "A999")


@responses.activate
def test_fetch_estacoes_filtra_por_uf():
    responses.add(
        responses.GET,
        ESTACOES_URL,
        json=[
            {"CD_ESTACAO": "A701", "DC_NOME": "SAO PAULO", "SG_ESTADO": "SP",
             "VL_LATITUDE": "-23.5", "VL_LONGITUDE": "-46.6", "CD_SITUACAO": "Operante"},
            {"CD_ESTACAO": "A001", "DC_NOME": "BRASILIA", "SG_ESTADO": "DF",
             "VL_LATITUDE": "-15.7", "VL_LONGITUDE": "-47.9", "CD_SITUACAO": "Operante"},
        ],
        status=200,
    )

    estacoes = fetch_estacoes("sp")

    assert len(estacoes) == 1
    assert estacoes[0].codigo == "A701"
    assert estacoes[0].uf == "SP"


@responses.activate
def test_baixar_zip_ano_condicional_baixa_e_retorna_etag(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    responses.add(
        responses.GET,
        "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip",
        body=b"conteudo do zip",
        status=200,
        headers={"ETag": '"abc123"'},
    )

    caminho, etag = baixar_zip_ano_condicional(2026, destino, etag_anterior=None)

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo do zip"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_reaproveita_cache_em_304(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    destino.write_bytes(b"conteudo em cache")

    responses.add(
        responses.GET,
        "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip",
        status=304,
    )

    caminho, etag = baixar_zip_ano_condicional(2026, destino, etag_anterior='"abc123"')

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo em cache"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_usa_cache_quando_download_falha(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    destino.write_bytes(b"conteudo em cache")

    responses.add(responses.GET, "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip", status=500)

    caminho, etag = baixar_zip_ano_condicional(
        2026, destino, etag_anterior='"abc123"', max_retries=1, backoff_factor=0.01
    )

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo em cache"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_sem_cache_levanta_erro(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"

    responses.add(responses.GET, "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip", status=500)

    with pytest.raises(INMETFetchError):
        baixar_zip_ano_condicional(2026, destino, etag_anterior=None, max_retries=1, backoff_factor=0.01)


def test_crc32_estacao_retorna_crc_sem_descompactar(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    crc = _crc32_estacao(zip_path, "SP", "A701")

    with zipfile.ZipFile(zip_path) as zf:
        crc_esperado = zf.getinfo(zf.namelist()[0]).CRC
    assert crc == crc_esperado


def test_crc32_estacao_retorna_none_se_estacao_nao_existe(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    assert _crc32_estacao(zip_path, "SP", "A999") is None


def test_manifesto_salvar_e_carregar_round_trip(tmp_path: Path):
    caminho = tmp_path / "inmet_manifest_sp_2026.json"
    manifesto = {
        "etag_zip": '"abc123"',
        "estacoes": {"A701": {"crc32": 999, "ultima_data_hora": "2026-08-05T23:00:00+00:00"}},
    }

    _salvar_manifesto(caminho, manifesto)
    carregado = _carregar_manifesto(caminho)

    assert carregado == manifesto


def test_manifesto_carregar_arquivo_inexistente_retorna_vazio(tmp_path: Path):
    caminho = tmp_path / "nao_existe.json"

    assert _carregar_manifesto(caminho) == {"etag_zip": None, "estacoes": {}}
