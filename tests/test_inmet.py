import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import responses
from responses import matchers

from src.ingest.inmet import (
    ESTACOES_URL,
    INMETFetchError,
    _carregar_manifesto,
    _crc32_estacao,
    _mesclar_serie_estacao,
    _parse_csv_estacao,
    _salvar_manifesto,
    baixar_zip_ano_condicional,
    fetch_estacoes,
    ingerir_uf,
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


def _csv_estacao(codigo: str, leituras: list[tuple[str, str, str]]) -> bytes:
    """Monta um CSV horário do INMET com as linhas de dado informadas (data, hora 'HHMM', precip)."""
    linhas_dados = "".join(f"{data};{hora} UTC;{precip};999\r\n" for data, hora, precip in leituras)
    return (
        "REGIAO:;SE\r\nUF:;SP\r\nESTACAO:;TESTE\r\n"
        f"CODIGO (WMO):;{codigo}\r\nLATITUDE:;-23,5\r\nLONGITUDE:;-46,6\r\n"
        "ALTITUDE:;800\r\nDATA DE FUNDACAO:;01/01/00\r\n"
        "Data;Hora UTC;PRECIPITACAO TOTAL, HORARIO (mm);OUTRA COLUNA\r\n"
        f"{linhas_dados}"
    ).encode("latin-1")


def _bytes_zip(conteudos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nome, conteudo in conteudos.items():
            zf.writestr(nome, conteudo)
    return buf.getvalue()


def _mock_estacoes(*codigos: str) -> list[dict]:
    return [
        {
            "CD_ESTACAO": codigo, "DC_NOME": f"ESTACAO {codigo}", "SG_ESTADO": "SP",
            "VL_LATITUDE": "-23.5", "VL_LONGITUDE": "-46.6", "CD_SITUACAO": "Operante",
        }
        for codigo in codigos
    ]


_NOME_ZIP_URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip"


def _nome_no_zip(codigo: str) -> str:
    return f"INMET_SE_SP_{codigo}_ESTACAO {codigo}_01-01-2026_A_09-08-2026.CSV"


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


@responses.activate
def test_ingerir_uf_primeira_execucao_processa_todas_as_estacoes(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    zip_v1 = _bytes_zip({
        _nome_no_zip("A701"): _csv_estacao("A701", [
            ("2026/08/01", "0000", "1,0"),
            ("2026/08/01", "0100", "2,0"),
        ]),
    })
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    resultado = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert len(resultado) == 2
    assert set(resultado["codigo_estacao"]) == {"A701"}


@responses.activate
def test_ingerir_uf_segunda_execucao_pula_estacao_sem_mudanca_e_mescla_a_que_mudou(
    tmp_path: Path, monkeypatch
):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701", "B002"), status=200)
    csv_a701 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0"), ("2026/08/01", "0100", "2,0")])
    csv_b002_v1 = _csv_estacao("B002", [("2026/08/01", "0000", "5,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_a701, _nome_no_zip("B002"): csv_b002_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    primeira = ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    assert len(primeira) == 3

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701", "B002"), status=200)
    csv_b002_v2 = _csv_estacao(
        "B002", [("2026/08/01", "0000", "5,0"), ("2026/08/01", "0200", "7,0")]
    )
    zip_v2 = _bytes_zip({_nome_no_zip("A701"): csv_a701, _nome_no_zip("B002"): csv_b002_v2})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v2, status=200, headers={"ETag": '"v2"'})

    chamadas_a701 = []
    original_ler_serie = ler_serie_estacao

    def _espiao(zip_path, uf, codigo):
        if codigo == "A701":
            chamadas_a701.append(codigo)
        return original_ler_serie(zip_path, uf, codigo)

    monkeypatch.setattr("src.ingest.inmet.ler_serie_estacao", _espiao)

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert chamadas_a701 == []
    assert len(segunda[segunda["codigo_estacao"] == "A701"]) == 2
    assert len(segunda[segunda["codigo_estacao"] == "B002"]) == 2


@responses.activate
def test_ingerir_uf_retificacao_dentro_da_janela_usa_valor_mais_novo(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v1 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    primeira = ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    assert primeira[primeira["codigo_estacao"] == "A701"]["chuva_mm"].iloc[0] == 1.0

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v2 = _csv_estacao("A701", [("2026/08/01", "0000", "9,9")])
    zip_v2 = _bytes_zip({_nome_no_zip("A701"): csv_v2})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v2, status=200, headers={"ETag": '"v2"'})

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    linha = segunda[segunda["codigo_estacao"] == "A701"]
    assert len(linha) == 1
    assert linha["chuva_mm"].iloc[0] == 9.9


@responses.activate
def test_ingerir_uf_preserva_linhas_fora_da_janela_de_retificacao(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v1 = _csv_estacao("A701", [
        ("2026/07/01", "0000", "1,0"),
        ("2026/08/01", "0000", "2,0"),
    ])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    primeira = ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    assert len(primeira) == 2

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    # v2 "retifica" a linha de 07/01 (fora da janela de 7 dias a partir de 08/01) e soma uma nova em 08/02
    csv_v2 = _csv_estacao("A701", [
        ("2026/07/01", "0000", "999,9"),
        ("2026/08/01", "0000", "2,0"),
        ("2026/08/02", "0000", "3,0"),
    ])
    zip_v2 = _bytes_zip({_nome_no_zip("A701"): csv_v2})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v2, status=200, headers={"ETag": '"v2"'})

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert len(segunda) == 3
    linha_antiga = segunda[segunda["data_hora"] == segunda["data_hora"].min()]
    assert linha_antiga["chuva_mm"].iloc[0] == 1.0  # fora da janela: não foi "retificada"


def _serie(pontos: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "data_hora": [pd.Timestamp(iso) for iso, _ in pontos],
        "chuva_mm": [mm for _, mm in pontos],
    })


def test_mesclar_serie_estacao_usa_valor_novo_dentro_da_janela():
    cutoff = pd.Timestamp("2026-08-01 00:00")
    existente = _serie([("2026-08-01 00:00", 1.0)])
    nova = _serie([("2026-08-01 00:00", 9.9)])

    resultado = _mesclar_serie_estacao(existente, nova, cutoff)

    assert len(resultado) == 1
    assert resultado["chuva_mm"].iloc[0] == 9.9


def test_mesclar_serie_estacao_preserva_valor_existente_fora_da_janela():
    cutoff = pd.Timestamp("2026-08-01 00:00")
    existente = _serie([("2026-07-01 00:00", 1.0)])
    nova = _serie([("2026-07-01 00:00", 999.9), ("2026-08-01 00:00", 2.0)])

    resultado = _mesclar_serie_estacao(existente, nova, cutoff)

    assert len(resultado) == 2
    linha_antiga = resultado[resultado["data_hora"] == pd.Timestamp("2026-07-01 00:00")]
    assert linha_antiga["chuva_mm"].iloc[0] == 1.0


def test_mesclar_serie_estacao_ordena_por_data_hora():
    cutoff = pd.Timestamp("2026-08-01 00:00")
    existente = _serie([("2026-07-01 00:00", 1.0)])
    nova = _serie([("2026-08-02 00:00", 3.0), ("2026-08-01 00:00", 2.0)])

    resultado = _mesclar_serie_estacao(existente, nova, cutoff)

    assert list(resultado["data_hora"]) == sorted(resultado["data_hora"])


@responses.activate
def test_ingerir_uf_reaproveita_zip_em_304(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v1 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    responses.add(responses.GET, _NOME_ZIP_URL, status=304)

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert len(segunda) == 1
    assert segunda["chuva_mm"].iloc[0] == 1.0


@responses.activate
def test_ingerir_uf_ignora_estacao_sem_leituras_validas(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701", "VAZIA"), status=200)
    csv_a701 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0")])
    csv_vazia = _csv_estacao("VAZIA", [])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_a701, _nome_no_zip("VAZIA"): csv_vazia})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    resultado = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert set(resultado["codigo_estacao"]) == {"A701"}


@responses.activate
def test_ingerir_uf_baixa_zip_de_novo_se_cache_local_sumiu(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v1 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    (tmp_path / "inmet_2026.zip").unlink()

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    # Se o código (incorretamente) mandasse If-None-Match mesmo sem o ZIP local, cairia aqui e quebraria.
    responses.add(
        responses.GET, _NOME_ZIP_URL,
        status=304,
        match=[matchers.header_matcher({"If-None-Match": '"v1"'})],
    )
    # Sem o cache local, o código correto não manda If-None-Match e cai aqui, recebendo o ZIP de novo.
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert len(segunda) == 1
