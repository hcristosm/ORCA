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

A cada execução, buscar o ano inteiro do zero seria caro sem necessidade: um
`HEAD` real no ZIP confirmou que o servidor suporta `Range`/`ETag`, mas cada
estação tem um único arquivo cobrindo o ano inteiro — não há como pedir só
"os últimos N dias" de uma estação ao servidor. A otimização é inteiramente
local (ver docs/superpowers/specs/2026-08-09-ingestao-inmet-incremental-design.md):
o ZIP é baixado com GET condicional (pula a transferência se não mudou desde
a última execução) e, por estação, o CRC32 da entrada no ZIP é comparado a
um manifesto local (`data/inmet_manifest_<uf>_<ano>.json`) — sem mudança,
pula o reprocessamento; com mudança, mescla só os últimos 7 dias (janela de
retificação) no CSV acumulado em vez de reparsear o ano inteiro.

O registro de estações (`/estacoes/T`) é servido sem proteção de bot e é usado
para obter latitude/longitude de cada estação automática.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from src.config import caminho_chuva, caminho_manifesto_inmet, caminho_zip_inmet
from src.storage import ler_chuva, salvar_chuva

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
    headers_extra: dict[str, str] | None = None,
    **kwargs,
) -> requests.Response:
    headers = {**_HEADERS, **(headers_extra or {})}
    last_exc: Exception | None = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=timeout, **kwargs)
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


def baixar_zip_ano_condicional(
    ano: int,
    destino: Path,
    etag_anterior: str | None,
    timeout: float = 120.0,
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    session: requests.Session | None = None,
) -> tuple[Path, str | None]:
    """Baixa o ZIP anual do INMET com GET condicional (`If-None-Match`).

    O ZIP anual do INMET não permite baixar só um intervalo de datas: cada
    estação tem um único arquivo cobrindo o ano inteiro, sem granularidade
    por dia ou mês no lado do servidor (não há como pedir só "os últimos N
    dias" de uma estação). O GET condicional aqui só evita retransferir os
    mesmos ~55MB quando o arquivo não mudou nada desde a última execução
    (`etag_anterior` bate com o ETag atual do servidor, HTTP 304); não
    reduz o tamanho do download quando o arquivo de fato mudou, que é o
    caso normal do cron diário. A otimização real de reprocessamento vem do
    CRC32 por estação (ver `_crc32_estacao`), não de baixar menos bytes.

    Retorna o caminho do ZIP e o ETag atual (pode ser `None` se o servidor
    não enviar um, ou se a fonte remota falhar e um ZIP em cache local for
    reaproveitado).
    """
    sess = session or requests.Session()
    url = ZIP_URL_TEMPLATE.format(ano=ano)
    headers_extra = (
        {"If-None-Match": etag_anterior} if etag_anterior and destino.exists() else None
    )

    try:
        resp = _get_com_retry(
            url, sess, timeout, max_retries, backoff_factor,
            headers_extra=headers_extra, stream=True,
        )
    except INMETFetchError:
        if destino.exists():
            logger.warning(
                "Fonte remota do INMET indisponível; usando ZIP em cache local em %s", destino
            )
            return destino, etag_anterior
        raise

    if resp.status_code == 304:
        logger.info(
            "ZIP do INMET para %d não mudou desde a última execução (ETag igual); "
            "reaproveitando cache local em %s.", ano, destino,
        )
        return destino, etag_anterior

    destino.parent.mkdir(parents=True, exist_ok=True)
    with open(destino, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    return destino, resp.headers.get("ETag")


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


def _nome_arquivo_no_zip(zf: zipfile.ZipFile, uf: str, codigo: str) -> str:
    alvo = _nome_arquivo_estacao(uf, codigo)
    candidatos = [n for n in zf.namelist() if alvo in n.upper()]
    if not candidatos:
        raise INMETFetchError(f"Estação {uf}/{codigo} não encontrada em {zf.filename}")
    return candidatos[0]


def _crc32_estacao(zip_path: Path, uf: str, codigo: str) -> int | None:
    """CRC32 da entrada da estação no ZIP, sem descompactar (None se a estação não estiver no ZIP)."""
    with zipfile.ZipFile(zip_path) as zf:
        try:
            nome = _nome_arquivo_no_zip(zf, uf, codigo)
        except INMETFetchError:
            return None
        return zf.getinfo(nome).CRC


def ler_serie_estacao(zip_path: Path, uf: str, codigo: str) -> pd.DataFrame:
    """Extrai e faz o parsing da série horária de chuva de uma estação a partir do ZIP anual."""
    with zipfile.ZipFile(zip_path) as zf:
        nome = _nome_arquivo_no_zip(zf, uf, codigo)
        with zf.open(nome) as f:
            conteudo = f.read()
    return _parse_csv_estacao(conteudo)


def _carregar_manifesto(caminho: Path) -> dict:
    if not caminho.exists():
        return {"etag_zip": None, "estacoes": {}}
    try:
        return json.loads(caminho.read_text())
    except json.JSONDecodeError:
        logger.warning("Manifesto corrompido em %s; tratando como inexistente.", caminho)
        return {"etag_zip": None, "estacoes": {}}


def _salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))


JANELA_RETIFICACAO = pd.Timedelta(days=7)


def _mesclar_serie_estacao(
    serie_existente: pd.DataFrame, serie_nova: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Funde a série já salva de uma estação com a recém-baixada, na janela de retificação.

    Antes de `cutoff`, os dados existentes são tratados como estáveis e
    preservados; a partir de `cutoff` (inclusive), a leitura mais recente
    baixada prevalece em caso de retificação (mesmo `data_hora`, `chuva_mm`
    diferente) — ver docstring do módulo para a estratégia incremental.
    """
    antigas_estaveis = serie_existente[serie_existente["data_hora"] < cutoff]
    recentes_novas = serie_nova[serie_nova["data_hora"] >= cutoff]
    return (
        pd.concat([antigas_estaveis, recentes_novas], ignore_index=True)
        .drop_duplicates(subset="data_hora", keep="last")
        .sort_values("data_hora")
        .reset_index(drop=True)
    )


def ingerir_uf(
    uf: str,
    ano: int,
    diretorio_dados: Path,
    timeout: float = 120.0,
    max_retries: int = 3,
) -> pd.DataFrame:
    """Baixa (incrementalmente) o ZIP anual do INMET e monta uma série horária de
    chuva para todas as estações automáticas de uma UF, salvando o resultado em CSV.

    Ver docstring do módulo para a estratégia incremental (GET condicional do
    ZIP + CRC32 por estação + manifesto). Dentro da janela de retificação de
    `JANELA_RETIFICACAO` (7 dias) a partir da última leitura já salva de uma
    estação, o valor mais recente baixado prevalece em caso de retificação
    (mesmo `data_hora`, `chuva_mm` diferente); fora dessa janela, os dados já
    salvos são tratados como estáveis.
    """
    uf_norm = uf.strip().upper()
    zip_path = caminho_zip_inmet(ano, diretorio_dados)
    manifesto_path = caminho_manifesto_inmet(uf_norm, ano, diretorio_dados)
    manifesto = _carregar_manifesto(manifesto_path)

    zip_path, etag_novo = baixar_zip_ano_condicional(
        ano, zip_path, manifesto.get("etag_zip"), timeout=timeout, max_retries=max_retries
    )

    estacoes = fetch_estacoes(uf_norm, max_retries=max_retries)

    saida = caminho_chuva(uf_norm, ano, diretorio_dados)
    existente = None
    if saida.exists():
        try:
            existente = ler_chuva(saida)
            if existente.empty:
                existente = None
        except pd.errors.EmptyDataError:
            logger.warning(
                "CSV acumulado em %s está vazio ou corrompido; tratando como inexistente.", saida
            )
            existente = None
    manifesto_estacoes = manifesto.get("estacoes", {})

    partes = []
    novo_manifesto_estacoes = {}
    for estacao in estacoes:
        serie_existente_estacao = None
        if existente is not None:
            candidata = existente[existente["codigo_estacao"] == estacao.codigo]
            if not candidata.empty:
                serie_existente_estacao = candidata

        crc_atual = _crc32_estacao(zip_path, uf_norm, estacao.codigo)
        if crc_atual is None:
            logger.warning("Sem dados no ZIP para a estação %s/%s", uf_norm, estacao.codigo)
            if serie_existente_estacao is not None:
                partes.append(serie_existente_estacao)
                entrada_anterior = manifesto_estacoes.get(estacao.codigo)
                if entrada_anterior:
                    novo_manifesto_estacoes[estacao.codigo] = entrada_anterior
            continue

        entrada_anterior = manifesto_estacoes.get(estacao.codigo)
        if (
            entrada_anterior is not None
            and entrada_anterior.get("crc32") == crc_atual
            and serie_existente_estacao is not None
        ):
            serie_final = serie_existente_estacao.copy()
            serie_final["nome_estacao"] = estacao.nome
            serie_final["uf"] = estacao.uf
            serie_final["latitude"] = estacao.latitude
            serie_final["longitude"] = estacao.longitude
        else:
            serie_nova = ler_serie_estacao(zip_path, uf_norm, estacao.codigo).reset_index()
            serie_nova["codigo_estacao"] = estacao.codigo
            serie_nova["nome_estacao"] = estacao.nome
            serie_nova["uf"] = estacao.uf
            serie_nova["latitude"] = estacao.latitude
            serie_nova["longitude"] = estacao.longitude

            if serie_existente_estacao is None:
                serie_final = serie_nova
            else:
                cutoff = serie_existente_estacao["data_hora"].max() - JANELA_RETIFICACAO
                serie_final = _mesclar_serie_estacao(serie_existente_estacao, serie_nova, cutoff)

        if serie_final.empty:
            logger.warning(
                "Estação %s/%s sem leituras válidas nesta execução; ignorando.",
                uf_norm, estacao.codigo,
            )
            continue

        partes.append(serie_final)
        novo_manifesto_estacoes[estacao.codigo] = {
            "crc32": crc_atual,
            "ultima_data_hora": serie_final["data_hora"].max().isoformat(),
        }

    if not partes:
        raise INMETFetchError(f"Nenhuma estação com dados encontrada para UF={uf_norm}")

    resultado = (
        pd.concat(partes, ignore_index=True)
        .sort_values(["codigo_estacao", "data_hora"])
        .reset_index(drop=True)
    )
    salvar_chuva(resultado, saida)
    _salvar_manifesto(manifesto_path, {"etag_zip": etag_novo, "estacoes": novo_manifesto_estacoes})

    logger.info(
        "Salvas %d leituras horárias de %d estações de %s em %s",
        len(resultado), len(partes), uf_norm, saida,
    )
    return resultado
