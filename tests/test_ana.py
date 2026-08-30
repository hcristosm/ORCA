from pathlib import Path

import pandas as pd
import pytest
import responses
from responses import matchers

from src.ingest.ana import (
    DADOS_URL,
    LISTA_ESTACOES_URL,
    ANAFetchError,
    _tem_dado_recente,
    fetch_estacoes,
    fetch_serie_estacao,
    ingerir_uf,
)

XML_ESTACOES_SP_E_RJ = b"""<?xml version="1.0" encoding="utf-8"?>
<DataTable>
  <Table>
    <CodEstacao>58040000</CodEstacao>
    <NomeEstacao>SAO LUIS DO PARAITINGA</NomeEstacao>
    <Municipio-UF>SAO LUIS DO PARAITINGA-SP</Municipio-UF>
    <Latitude>-23.35</Latitude>
    <Longitude>-45.25</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
  <Table>
    <CodEstacao>99999999</CodEstacao>
    <NomeEstacao>OUTRA CIDADE</NomeEstacao>
    <Municipio-UF>OUTRA CIDADE-RJ</Municipio-UF>
    <Latitude>-22.9</Latitude>
    <Longitude>-43.2</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
</DataTable>
"""


def _xml_dados(leituras: list[tuple[str, str]]) -> bytes:
    """leituras: lista de (data_hora, chuva) como strings, no formato do serviço."""
    linhas = "".join(
        f"<DadosHidrometereologicos><DataHora>{dh}</DataHora>"
        f"<Chuva>{chuva}</Chuva></DadosHidrometereologicos>"
        for dh, chuva in leituras
    )
    return f'<?xml version="1.0" encoding="utf-8"?><DataTable>{linhas}</DataTable>'.encode()


@responses.activate
def test_fetch_estacoes_filtra_por_sufixo_de_uf():
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=XML_ESTACOES_SP_E_RJ, status=200)

    estacoes = fetch_estacoes("SP")

    assert len(estacoes) == 1
    assert estacoes[0].codigo == "58040000"
    assert estacoes[0].municipio_uf == "SAO LUIS DO PARAITINGA-SP"


@responses.activate
def test_fetch_estacoes_retry_recupera_apos_falha_transitoria():
    responses.add(responses.GET, LISTA_ESTACOES_URL, status=500)
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=XML_ESTACOES_SP_E_RJ, status=200)

    estacoes = fetch_estacoes("SP", max_retries=2, backoff_factor=0.01)

    assert len(estacoes) == 1


@responses.activate
def test_fetch_estacoes_falha_persistente_levanta_erro():
    responses.add(responses.GET, LISTA_ESTACOES_URL, status=500)

    with pytest.raises(ANAFetchError):
        fetch_estacoes("SP", max_retries=2, backoff_factor=0.01)


@responses.activate
def test_fetch_serie_estacao_parseia_leituras_ordenadas_por_data():
    xml = _xml_dados([("2026-08-09 10:15:00", "1.2"), ("2026-08-09 10:00:00", "0,6")])
    responses.add(responses.GET, DADOS_URL, body=xml, status=200)

    serie = fetch_serie_estacao("58040000", dias_historico=1)

    assert len(serie) == 2
    assert serie["data_hora"].is_monotonic_increasing
    assert serie["chuva_mm"].tolist() == [0.6, 1.2]


@responses.activate
def test_fetch_serie_estacao_retry_recupera_apos_429():
    responses.add(responses.GET, DADOS_URL, status=429)
    responses.add(
        responses.GET, DADOS_URL, body=_xml_dados([("2026-08-09 10:00:00", "2.0")]), status=200
    )

    serie = fetch_serie_estacao("58040000", dias_historico=1, max_retries=3, backoff_factor=0.01)

    assert len(serie) == 1
    assert serie["chuva_mm"].iloc[0] == 2.0


@responses.activate
def test_fetch_serie_estacao_falha_persistente_retorna_vazio():
    responses.add(responses.GET, DADOS_URL, status=500)

    serie = fetch_serie_estacao("58040000", dias_historico=1, max_retries=2, backoff_factor=0.01)

    assert serie.empty


def test_tem_dado_recente_verdadeiro_para_leitura_dentro_da_janela():
    agora = pd.Timestamp.now(tz="UTC")
    serie = pd.DataFrame({"data_hora": [agora - pd.Timedelta(hours=1)], "chuva_mm": [1.0]})

    assert _tem_dado_recente(serie, janela_horas=48) is True


def test_tem_dado_recente_falso_para_leitura_fora_da_janela_ou_serie_vazia():
    agora = pd.Timestamp.now(tz="UTC")
    serie_antiga = pd.DataFrame({"data_hora": [agora - pd.Timedelta(hours=100)], "chuva_mm": [1.0]})
    serie_vazia = pd.DataFrame(columns=["data_hora", "chuva_mm"])

    assert _tem_dado_recente(serie_antiga, janela_horas=48) is False
    assert _tem_dado_recente(serie_vazia, janela_horas=48) is False


@responses.activate
def test_ingerir_uf_mantem_so_estacoes_com_dado_vivo_e_usa_schema_do_inmet(tmp_path: Path):
    xml_estacoes = b"""<?xml version="1.0" encoding="utf-8"?>
<DataTable>
  <Table>
    <CodEstacao>VIVA01</CodEstacao>
    <NomeEstacao>ESTACAO VIVA</NomeEstacao>
    <Municipio-UF>CIDADE A-SP</Municipio-UF>
    <Latitude>-23.35</Latitude>
    <Longitude>-45.25</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
  <Table>
    <CodEstacao>MORTA01</CodEstacao>
    <NomeEstacao>ESTACAO SEM DADO RECENTE</NomeEstacao>
    <Municipio-UF>CIDADE B-SP</Municipio-UF>
    <Latitude>-23.40</Latitude>
    <Longitude>-45.30</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
</DataTable>
"""
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=xml_estacoes, status=200)

    agora = pd.Timestamp.now(tz="UTC")
    leitura_recente = agora.strftime("%Y-%m-%d %H:%M:%S")
    leitura_antiga = (agora - pd.Timedelta(hours=200)).strftime("%Y-%m-%d %H:%M:%S")

    responses.add(
        responses.GET, DADOS_URL,
        body=_xml_dados([(leitura_recente, "3.0")]),
        status=200,
        match=[matchers.query_param_matcher({"codEstacao": "VIVA01"}, strict_match=False)],
    )
    responses.add(
        responses.GET, DADOS_URL,
        body=_xml_dados([(leitura_antiga, "1.0")]),
        status=200,
        match=[matchers.query_param_matcher({"codEstacao": "MORTA01"}, strict_match=False)],
    )

    resultado = ingerir_uf("SP", tmp_path, janela_horas=48, max_workers=1)

    assert set(resultado["codigo_estacao"]) == {"VIVA01"}
    assert list(resultado.columns) == [
        "data_hora", "chuva_mm", "codigo_estacao", "nome_estacao", "uf", "latitude", "longitude",
    ]
    assert (tmp_path / "chuva_ana_sp.csv").exists()


@responses.activate
def test_ingerir_uf_levanta_erro_se_nenhuma_estacao_tem_dado_vivo(tmp_path: Path):
    xml_estacoes = b"""<?xml version="1.0" encoding="utf-8"?>
<DataTable>
  <Table>
    <CodEstacao>MORTA01</CodEstacao>
    <NomeEstacao>ESTACAO SEM DADO RECENTE</NomeEstacao>
    <Municipio-UF>CIDADE B-SP</Municipio-UF>
    <Latitude>-23.40</Latitude>
    <Longitude>-45.30</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
</DataTable>
"""
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=xml_estacoes, status=200)
    responses.add(responses.GET, DADOS_URL, body=_xml_dados([]), status=200)

    with pytest.raises(ANAFetchError):
        ingerir_uf("SP", tmp_path, janela_horas=48, max_workers=1)


@responses.activate
def test_ingerir_uf_muitas_falhas_de_serie_levanta_erro_distinto_de_sem_dado_vivo(tmp_path: Path):
    xml_estacoes = b"""<?xml version="1.0" encoding="utf-8"?>
<DataTable>
  <Table>
    <CodEstacao>FALHA01</CodEstacao>
    <NomeEstacao>ESTACAO A</NomeEstacao>
    <Municipio-UF>CIDADE A-SP</Municipio-UF>
    <Latitude>-23.35</Latitude>
    <Longitude>-45.25</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
  <Table>
    <CodEstacao>FALHA02</CodEstacao>
    <NomeEstacao>ESTACAO B</NomeEstacao>
    <Municipio-UF>CIDADE B-SP</Municipio-UF>
    <Latitude>-23.40</Latitude>
    <Longitude>-45.30</Longitude>
    <StatusEstacao>Ativo</StatusEstacao>
  </Table>
</DataTable>
"""
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=xml_estacoes, status=200)
    responses.add(responses.GET, DADOS_URL, status=500)

    with pytest.raises(ANAFetchError, match="instabilidade do serviço"):
        ingerir_uf("SP", tmp_path, janela_horas=48, max_workers=1, max_retries=1, backoff_factor=0.01)


@responses.activate
def test_ingerir_uf_respeita_orcamento_de_tempo(tmp_path: Path):
    import time as time_module

    xml_estacoes = XML_ESTACOES_SP_E_RJ  # reaproveita a estação SP já definida no topo do arquivo
    responses.add(responses.GET, LISTA_ESTACOES_URL, body=xml_estacoes, status=200)
    responses.add(responses.GET, DADOS_URL, body=_xml_dados([]), status=200)

    inicio = time_module.monotonic()
    with pytest.raises(ANAFetchError):
        ingerir_uf("SP", tmp_path, janela_horas=48, max_workers=1, orcamento_tempo_s=0.0)
    duracao = time_module.monotonic() - inicio

    assert duracao < 5.0
