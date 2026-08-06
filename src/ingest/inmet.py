"""Cliente de ingestão de dados pluviométricos do INMET.

O pedido original previa usar o CEMADEN para chuva, mas a investigação (ver
README) mostrou que as únicas fontes do CEMADEN sem captcha que encontramos
são espelhos estáticos de 2017/2019 — não uma fonte viva. A API dinâmica do
INMET (`apitempo.inmet.gov.br/estacao/...`) também não é viável sem navegador:
está atrás de um WAF (cookies `TS...`, indicativo de F5 Bot Defense) que
devolve HTTP 204 vazio para clientes não-navegador em vez de um erro claro.

A fonte usada aqui é o pacote **anual de dados históricos** que o INMET
publica como ZIP público, sem captcha nem bloqueio de bot:
https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip

Cada ZIP contém um CSV por estação automática, com leituras horárias (incluindo
precipitação) desde 1º de janeiro do ano até poucos dias antes do download —
ou seja, não é "tempo real" no sentido estrito, mas é a chuva real mais recente
disponível publicamente sem intervenção manual. Essa defasagem é documentada
no README como limitação conhecida.

O registro de estações (`/estacoes/T`) é servido sem proteção de bot e é usado
para obter latitude/longitude de cada estação automática.
"""

from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from src.config import caminho_chuva, caminho_zip_inmet
from src.storage import salvar_chuva

logger = logging.getLogger(__name__)

ESTACOES_URL = "https://apitempo.inmet.gov.br/estacoes/T"
ZIP_URL_TEMPLATE = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{ano}.zip"

# A API do INMET bloqueia clientes sem um User-Agent de navegador.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class INMETFetchError(RuntimeError):
    """Erro ao buscar dados do INMET."""


@dataclass(frozen=True)
class Estacao:
    codigo: str
    nome: str
    uf: str
    latitude: float
    longitude: float
    situacao: str


def _get_com_retry(
    url: str,
    session: requests.Session,
    timeout: float,
    max_retries: int,
    backoff_factor: float,
    **kwargs,
) -> requests.Response:
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=_HEADERS, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            espera = backoff_factor * (2 ** (tentativa - 1))
            logger.warning(
                "Falha ao acessar %s (tentativa %d/%d): %s. Aguardando %.1fs.",
                url, tentativa, max_retries, exc, espera,
            )
            if tentativa < max_retries:
                time.sleep(espera)

    raise INMETFetchError(f"Não foi possível acessar {url} após {max_retries} tentativas") from last_exc


def fetch_estacoes(
    uf: str | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    session: requests.Session | None = None,
) -> list[Estacao]:
    """Lista as estações meteorológicas automáticas do INMET (opcionalmente filtrando por UF)."""
    sess = session or requests.Session()
    resp = _get_com_retry(ESTACOES_URL, sess, timeout, max_retries, backoff_factor)
    dados = resp.json()

    estacoes = [
        Estacao(
            codigo=item["CD_ESTACAO"],
            nome=item["DC_NOME"],
            uf=item["SG_ESTADO"],
            latitude=float(item["VL_LATITUDE"]),
            longitude=float(item["VL_LONGITUDE"]),
            situacao=item["CD_SITUACAO"],
        )
        for item in dados
        if item.get("VL_LATITUDE") and item.get("VL_LONGITUDE")
    ]
    if uf is not None:
        uf_norm = uf.strip().upper()
        estacoes = [e for e in estacoes if e.uf == uf_norm]
    return estacoes


def baixar_zip_ano(
    ano: int,
    destino: Path,
    timeout: float = 120.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> Path:
    """Baixa (ou reaproveita do cache local) o ZIP anual de dados históricos do INMET."""
    sess = session or requests.Session()
    url = ZIP_URL_TEMPLATE.format(ano=ano)

    try:
        resp = _get_com_retry(url, sess, timeout, max_retries, backoff_factor, stream=True)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        return destino
    except INMETFetchError:
        if destino.exists():
            logger.warning(
                "Fonte remota do INMET indisponível; usando ZIP em cache local em %s", destino
            )
            return destino
        raise


def _nome_arquivo_estacao(uf: str, codigo: str) -> str:
    return f"_{uf.upper()}_{codigo.upper()}_"


def _parse_csv_estacao(conteudo: bytes) -> pd.DataFrame:
    """Faz o parsing de um CSV horário do INMET (latin-1, ';', decimal ',', 8 linhas de metadados)."""
    texto = conteudo.decode("latin-1")
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    linhas = list(leitor)

    linhas_dados = linhas[9:]  # 8 linhas de metadados + 1 de cabeçalho de colunas

    registros = []
    for linha in linhas_dados:
        if len(linha) < 3 or not linha[0]:
            continue
        data_str, hora_str, precip_str = linha[0], linha[1], linha[2]
        try:
            data_hora = pd.to_datetime(
                f"{data_str} {hora_str[:4]}", format="%Y/%m/%d %H%M", utc=True
            )
        except ValueError:
            continue
        precip = precip_str.strip().replace(",", ".")
        chuva_mm = float(precip) if precip not in ("", "NULL", "-9999") else float("nan")
        registros.append((data_hora, chuva_mm))

    return pd.DataFrame(registros, columns=["data_hora", "chuva_mm"]).set_index("data_hora")


def ler_serie_estacao(zip_path: Path, uf: str, codigo: str) -> pd.DataFrame:
    """Extrai e faz o parsing da série horária de chuva de uma estação a partir do ZIP anual."""
    alvo = _nome_arquivo_estacao(uf, codigo)
    with zipfile.ZipFile(zip_path) as zf:
        candidatos = [n for n in zf.namelist() if alvo in n.upper()]
        if not candidatos:
            raise INMETFetchError(f"Estação {uf}/{codigo} não encontrada em {zip_path}")
        with zf.open(candidatos[0]) as f:
            conteudo = f.read()

    return _parse_csv_estacao(conteudo)


def ingerir_uf(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Baixa o ZIP anual do INMET e monta uma série horária de chuva para todas as
    estações automáticas de uma UF, salvando o resultado em CSV.
    """
    uf_norm = uf.strip().upper()
    zip_path = caminho_zip_inmet(ano, diretorio_dados)
    baixar_zip_ano(ano, zip_path, timeout=timeout, max_retries=max_retries)

    estacoes = fetch_estacoes(uf_norm, max_retries=max_retries)

    partes = []
    for estacao in estacoes:
        try:
            serie = ler_serie_estacao(zip_path, uf_norm, estacao.codigo)
        except INMETFetchError:
            logger.warning("Sem dados no ZIP para a estação %s/%s", uf_norm, estacao.codigo)
            continue
        serie["codigo_estacao"] = estacao.codigo
        serie["nome_estacao"] = estacao.nome
        serie["uf"] = estacao.uf
        serie["latitude"] = estacao.latitude
        serie["longitude"] = estacao.longitude
        partes.append(serie.reset_index())

    if not partes:
        raise INMETFetchError(f"Nenhuma estação com dados encontrada para UF={uf_norm}")

    resultado = pd.concat(partes, ignore_index=True)
    saida = caminho_chuva(uf_norm, ano, diretorio_dados)
    salvar_chuva(resultado, saida)
    logger.info(
        "Salvas %d leituras horárias de %d estações de %s em %s",
        len(resultado), len(partes), uf_norm, saida,
    )
    return resultado
