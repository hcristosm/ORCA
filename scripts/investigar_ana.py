"""Levantamento de cobertura da rede telemétrica da ANA em SP.

Pré-requisito identificado no README (ver "Investigação: fontes de chuva em
tempo real") antes de decidir se a rede telemétrica da ANA
(https://telemetriaws1.ana.gov.br/ServiceANA.asmx) vale a pena integrar como
fonte complementar ao INMET: nem toda estação listada como "Ativo" transmite
dado recente por esse serviço. Este script varre as estações de uma UF, mede
quantas têm leitura de chuva nas últimas N horas e, para as que têm, calcula a
distância até o setor de risco mais próximo (reaproveitando o GeoPackage já
baixado por `ingest-cprm`).

Uso:
    python scripts/investigar_ana.py --uf SP
    python scripts/investigar_ana.py --uf SP --janela-horas 48 --max-workers 10

Não faz parte do pipeline de ingestão do ORCA (ainda), é uma ferramenta de
investigação avulsa. Se a cobertura resultante compensar, o próximo passo é
promover isso a um cliente em `src/ingest/ana.py`.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR, caminho_setores  # noqa: E402
from src.processing.cruzamento import CRS_METRICO  # noqa: E402
from src.storage import ler_setores  # noqa: E402

logger = logging.getLogger(__name__)

BASE_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"
LISTA_ESTACOES_URL = f"{BASE_URL}/ListaEstacoesTelemetricas"
DADOS_URL = f"{BASE_URL}/DadosHidrometeorologicos"

_NS = {"": "http://MRCS/"}


@dataclass
class EstacaoANA:
    codigo: str
    nome: str
    municipio_uf: str
    latitude: float
    longitude: float
    status: str


def _parse_float(texto: str | None) -> float | None:
    if texto is None or texto.strip() == "":
        return None
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        return None


def fetch_estacoes_ana(
    uf: str,
    timeout: float = 60.0,
    session: requests.Session | None = None,
) -> list[EstacaoANA]:
    """Lista todas as estações telemétricas da ANA e filtra por UF (Municipio-UF)."""
    sess = session or requests.Session()
    resp = sess.get(
        LISTA_ESTACOES_URL, params={"statusEstacoes": "", "origem": ""}, timeout=timeout
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    sufixo = f"-{uf.upper()}"
    estacoes = []
    for tabela in root.iter():
        if not tabela.tag.endswith("Table"):
            continue
        municipio_uf = (tabela.findtext("Municipio-UF") or "").strip()
        if not municipio_uf.upper().endswith(sufixo):
            continue
        lat = _parse_float(tabela.findtext("Latitude"))
        lon = _parse_float(tabela.findtext("Longitude"))
        if lat is None or lon is None:
            continue
        estacoes.append(
            EstacaoANA(
                codigo=(tabela.findtext("CodEstacao") or "").strip(),
                nome=(tabela.findtext("NomeEstacao") or "").strip(),
                municipio_uf=municipio_uf,
                latitude=lat,
                longitude=lon,
                status=(tabela.findtext("StatusEstacao") or "").strip(),
            )
        )
    return estacoes


def fetch_ultima_leitura(
    codigo: str,
    janela_horas: int,
    timeout: float = 20.0,
    session: requests.Session | None = None,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
) -> datetime | None:
    """Retorna o timestamp da leitura mais recente de chuva da estação nas últimas `janela_horas`, ou None.

    Faz retry com backoff em erro de rede/HTTP (inclusive 429 Too Many Requests, que o
    serviço da ANA devolve com facilidade sob concorrência) para não confundir
    "rate limit" com "estação sem dado vivo".
    """
    sess = session or requests.Session()
    agora = datetime.now(timezone.utc)
    data_fim = agora.strftime("%d/%m/%Y")
    data_inicio = (agora - timedelta(hours=janela_horas)).strftime("%d/%m/%Y")

    root = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = sess.get(
                DADOS_URL,
                params={"codEstacao": codigo, "dataInicio": data_inicio, "dataFim": data_fim},
                timeout=timeout,
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            break
        except (requests.RequestException, ET.ParseError) as exc:
            espera = backoff_factor * (2 ** (tentativa - 1))
            if tentativa < max_retries:
                logger.debug(
                    "Falha ao consultar estação %s (tentativa %d/%d): %s. Aguardando %.1fs.",
                    codigo, tentativa, max_retries, exc, espera,
                )
                time.sleep(espera)
            else:
                logger.warning(
                    "Falha ao consultar estação %s após %d tentativas: %s",
                    codigo, max_retries, exc,
                )
                return None

    if root is None:
        return None

    timestamps = []
    for linha in root.iter("DadosHidrometereologicos"):
        chuva = linha.findtext("Chuva")
        data_hora = linha.findtext("DataHora")
        if chuva is None or data_hora is None:
            continue
        try:
            ts = datetime.strptime(data_hora.strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        timestamps.append(ts)

    if not timestamps:
        return None
    return max(timestamps).replace(tzinfo=timezone.utc)


def levantar_cobertura(
    uf: str,
    janela_horas: int,
    max_workers: int,
) -> pd.DataFrame:
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
    session.mount("https://", adapter)
    estacoes = fetch_estacoes_ana(uf, session=session)
    logger.info("%d estações da ANA listadas para %s", len(estacoes), uf)

    linhas = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {
            pool.submit(fetch_ultima_leitura, e.codigo, janela_horas, session=session): e
            for e in estacoes
        }
        for i, futuro in enumerate(as_completed(futuros), start=1):
            estacao = futuros[futuro]
            ultima_leitura = futuro.result()
            linhas.append(
                {
                    "codigo": estacao.codigo,
                    "nome": estacao.nome,
                    "municipio_uf": estacao.municipio_uf,
                    "status": estacao.status,
                    "latitude": estacao.latitude,
                    "longitude": estacao.longitude,
                    "ultima_leitura_utc": ultima_leitura,
                    "tem_dado_vivo": ultima_leitura is not None,
                }
            )
            if i % 50 == 0 or i == len(estacoes):
                logger.info("Consultadas %d/%d estações", i, len(estacoes))

    return pd.DataFrame(linhas)


def calcular_distancias(df_cobertura: pd.DataFrame, setores: gpd.GeoDataFrame) -> pd.DataFrame:
    """Para as estações com dado vivo, calcula a distância até o setor de risco mais próximo."""
    vivas = df_cobertura[df_cobertura["tem_dado_vivo"]].copy()
    if vivas.empty:
        df_cobertura["distancia_setor_mais_proximo_km"] = float("nan")
        return df_cobertura

    geometry = [Point(lon, lat) for lon, lat in zip(vivas["longitude"], vivas["latitude"])]
    estacoes_gdf = gpd.GeoDataFrame(vivas, geometry=geometry, crs="EPSG:4326").to_crs(CRS_METRICO)

    centroides = setores.to_crs(CRS_METRICO)
    centroides = centroides.set_geometry(centroides.geometry.centroid)

    pareado = gpd.sjoin_nearest(
        estacoes_gdf, centroides[["geometry"]], how="left", distance_col="distancia_m"
    )
    pareado = pareado[~pareado.index.duplicated(keep="first")]

    df_cobertura = df_cobertura.copy()
    df_cobertura["distancia_setor_mais_proximo_km"] = float("nan")
    df_cobertura.loc[pareado.index, "distancia_setor_mais_proximo_km"] = (
        pareado["distancia_m"] / 1000
    ).round(2)
    return df_cobertura


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uf", default="SP", help="Sigla da UF, ex.: SP")
    parser.add_argument(
        "--janela-horas", type=int, default=48, help="Janela de recência considerada 'dado vivo'"
    )
    parser.add_argument("--max-workers", type=int, default=5, help="Requisições em paralelo")
    parser.add_argument(
        "--saida",
        type=Path,
        default=None,
        help="CSV de saída (padrão: data/investigacao_ana_<uf>.csv)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    df = levantar_cobertura(args.uf, args.janela_horas, args.max_workers)

    setores_path = caminho_setores(args.uf, DATA_DIR)
    if setores_path.exists():
        setores = ler_setores(setores_path)
        df = calcular_distancias(df, setores)
    else:
        logger.warning(
            "Nenhum GeoPackage de setores em %s; rode `ingest-cprm --uf %s` primeiro para "
            "calcular distância até os setores de risco.",
            setores_path, args.uf,
        )
        df["distancia_setor_mais_proximo_km"] = float("nan")

    saida = args.saida or DATA_DIR / f"investigacao_ana_{args.uf.lower()}.csv"
    saida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(saida, index=False)

    total = len(df)
    vivas = int(df["tem_dado_vivo"].sum())
    pct = (vivas / total * 100) if total else 0.0
    dist_media = df.loc[df["tem_dado_vivo"], "distancia_setor_mais_proximo_km"].mean()

    print()
    print(f"UF: {args.uf}  |  janela considerada 'dado vivo': últimas {args.janela_horas}h")
    print(f"Estações listadas: {total}")
    print(f"Estações com dado vivo: {vivas} ({pct:.1f}%)")
    if pd.notna(dist_media):
        print(f"Distância média até o setor de risco mais próximo: {dist_media:.1f} km")
    print(f"Detalhe salvo em: {saida}")


if __name__ == "__main__":
    main()
