"""Cliente de ingestão da rede telemétrica da ANA (Agência Nacional de Águas),
fonte complementar de chuva ao INMET.

Web service: https://telemetriaws1.ana.gov.br/ServiceANA.asmx — público, sem
captcha, sem autenticação. `ListaEstacoesTelemetricas` lista as estações de
uma UF; `DadosHidrometeorologicos` devolve leituras de chuva em intervalos de
15 minutos por estação.

O levantamento em scripts/investigar_ana.py (ver README) mostrou que nem toda
estação listada como "Ativo" transmite dado recente: de 437 estações
cadastradas em SP, 271 (62%) tinham leitura de chuva nas últimas 48h. A
maioria das estações com dado vivo são hidrelétricas/fluviométricas (nomes
como "UHE ... BARRAMENTO/JUSANTE"), não pluviômetros dedicados — o campo
`Chuva` existe e responde, mas a rede não foi desenhada como uma rede
pluviométrica dedicada. Essa é uma limitação conhecida da fonte, não um bug
desta ingestão: o filtro de qualidade abaixo (`janela_horas`) só garante que
a estação está *viva*, não que ela é um pluviômetro de referência.
"""

from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from src.config import caminho_chuva_ana
from src.storage import ler_chuva, salvar_chuva

logger = logging.getLogger(__name__)

BASE_URL = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"
LISTA_ESTACOES_URL = f"{BASE_URL}/ListaEstacoesTelemetricas"
DADOS_URL = f"{BASE_URL}/DadosHidrometeorologicos"


class ANAFetchError(RuntimeError):
    """Erro ao buscar dados da rede telemétrica da ANA."""


@dataclass(frozen=True)
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


def fetch_estacoes(
    uf: str,
    timeout: float = 60.0,
    session: requests.Session | None = None,
    max_retries: int = 3,
    backoff_factor: float = 1.5,
) -> list[EstacaoANA]:
    """Lista as estações telemétricas da ANA cadastradas numa UF.

    Faz retry com backoff em erro de rede/HTTP (o serviço retorna 429 com
    facilidade sob concorrência — ver módulo docstring), levantando
    ANAFetchError se todas as tentativas falharem.
    """
    sess = session or requests.Session()

    root = None
    for tentativa in range(1, max_retries + 1):
        try:
            resp = sess.get(
                LISTA_ESTACOES_URL, params={"statusEstacoes": "", "origem": ""}, timeout=timeout
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            break
        except (requests.RequestException, ET.ParseError) as exc:
            espera = backoff_factor * (2 ** (tentativa - 1))
            if tentativa < max_retries:
                logger.debug(
                    "Falha ao listar estações da ANA para %s (tentativa %d/%d): %s. Aguardando %.1fs.",
                    uf, tentativa, max_retries, exc, espera,
                )
                time.sleep(espera)
            else:
                raise ANAFetchError(
                    f"Não foi possível listar estações da ANA para {uf} após {max_retries} tentativas"
                ) from exc

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


def fetch_serie_estacao(
    codigo: str,
    dias_historico: int = 4,
    timeout: float = 20.0,
    session: requests.Session | None = None,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
) -> pd.DataFrame:
    """Busca a série de chuva de uma estação nos últimos `dias_historico` dias.

    Faz retry com backoff em erro de rede/HTTP (inclusive 429 Too Many
    Requests, que o serviço da ANA devolve com facilidade sob concorrência —
    lógica validada com requisições reais em scripts/investigar_ana.py) para
    não confundir "rate limit" com "estação sem dado".

    Retorna um DataFrame com colunas `data_hora` (UTC) e `chuva_mm`, ordenado
    por data. Vazio se a estação não tiver nenhuma leitura no período ou se
    todas as tentativas falharem.
    """
    sess = session or requests.Session()
    agora = datetime.now(timezone.utc)
    data_fim = agora.strftime("%d/%m/%Y")
    data_inicio = (agora - timedelta(days=dias_historico)).strftime("%d/%m/%Y")

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
                return pd.DataFrame(columns=["data_hora", "chuva_mm"])

    registros = []
    for linha in root.iter("DadosHidrometereologicos"):
        chuva = linha.findtext("Chuva")
        data_hora = linha.findtext("DataHora")
        if chuva is None or data_hora is None:
            continue
        try:
            ts = pd.to_datetime(data_hora.strip(), format="%Y-%m-%d %H:%M:%S", utc=True)
        except ValueError:
            continue
        chuva_mm = _parse_float(chuva)
        if chuva_mm is None:
            continue
        registros.append((ts, chuva_mm))

    df = pd.DataFrame(registros, columns=["data_hora", "chuva_mm"])
    return df.sort_values("data_hora").reset_index(drop=True)


def _tem_dado_recente(serie: pd.DataFrame, janela_horas: int) -> bool:
    if serie.empty:
        return False
    limite = datetime.now(timezone.utc) - timedelta(hours=janela_horas)
    return bool((serie["data_hora"] >= limite).any())


def ingerir_uf(
    uf: str,
    diretorio_dados: Path,
    dias_historico: int = 4,
    janela_horas: int = 48,
    max_workers: int = 5,
    timeout: float = 20.0,
    max_retries: int = 5,
    backoff_factor: float = 1.5,
    orcamento_tempo_s: float = 900.0,
) -> pd.DataFrame:
    """Busca a chuva das estações telemétricas da ANA com dado vivo numa UF e
    salva em CSV.

    Só mantém estações com ao menos uma leitura nas últimas `janela_horas`
    (ver docstring do módulo sobre a ressalva de cobertura da rede). Formato
    de saída igual ao do INMET (`data_hora, chuva_mm, codigo_estacao,
    nome_estacao, uf, latitude, longitude`), permitindo `pd.concat` direto
    entre as duas fontes sem adaptador.

    `orcamento_tempo_s` (padrão 15min) limita o tempo total gasto consultando
    séries de estações: numa degradação generalizada do serviço da ANA, isso
    evita que a ingestão trave por horas e atrase as outras fontes no cron
    diário. Ao estourar o orçamento, a ingestão segue com o que já coletou até
    aquele ponto em vez de esperar todas as estações.
    """
    uf_norm = uf.strip().upper()
    saida = caminho_chuva_ana(uf_norm, diretorio_dados)

    try:
        estacoes = fetch_estacoes(uf_norm, timeout=timeout, max_retries=max_retries, backoff_factor=backoff_factor)
    except ANAFetchError as exc:
        if saida.exists():
            logger.warning(
                "Fonte remota da ANA indisponível; usando cache local em %s", saida
            )
            return ler_chuva(saida)
        raise ANAFetchError(f"Não foi possível listar estações da ANA para {uf_norm}") from exc

    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=max_workers, pool_maxsize=max_workers)
    session.mount("https://", adapter)

    partes = []
    falhas_series = 0
    inicio = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {
            pool.submit(
                fetch_serie_estacao,
                e.codigo, dias_historico, timeout, session, max_retries, backoff_factor,
            ): e
            for e in estacoes
        }
        for futuro in as_completed(futuros):
            if time.monotonic() - inicio > orcamento_tempo_s:
                logger.warning(
                    "Orçamento de tempo (%.0fs) excedido ao consultar séries da ANA; "
                    "interrompendo com %d estações já processadas de %d.",
                    orcamento_tempo_s, len(partes) + falhas_series, len(estacoes),
                )
                for f in futuros:
                    f.cancel()
                break
            estacao = futuros[futuro]
            serie = futuro.result()
            if serie.empty:
                falhas_series += 1
                continue
            if not _tem_dado_recente(serie, janela_horas):
                continue
            serie = serie.copy()
            serie["codigo_estacao"] = estacao.codigo
            serie["nome_estacao"] = estacao.nome
            serie["uf"] = uf_norm
            serie["latitude"] = estacao.latitude
            serie["longitude"] = estacao.longitude
            partes.append(serie)

    if not partes:
        total = len(estacoes)
        if total and falhas_series / total >= 0.5:
            if saida.exists():
                logger.warning(
                    "Muitas falhas ao consultar séries da ANA (%d/%d estações sem "
                    "resposta válida, possível instabilidade do serviço); usando "
                    "cache local em %s",
                    falhas_series, total, saida,
                )
                return ler_chuva(saida)
            raise ANAFetchError(
                f"Falha ao consultar dados da ANA para UF={uf_norm}: {falhas_series}/{total} "
                "estações sem resposta válida — possível instabilidade do serviço, não "
                "necessariamente falta de dado vivo."
            )
        raise ANAFetchError(f"Nenhuma estação da ANA com dado vivo encontrada para UF={uf_norm}")

    resultado = pd.concat(partes, ignore_index=True)
    salvar_chuva(resultado, saida)
    logger.info(
        "Salvas %d leituras de %d estações da ANA com dado vivo de %s em %s",
        len(resultado), len(partes), uf_norm, saida,
    )
    return resultado
