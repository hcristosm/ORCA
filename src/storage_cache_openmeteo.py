"""Cache local incremental para respostas horárias da Open-Meteo.

Ver docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md. Uma tabela
SQLite `(lat, lon, variavel, data_hora) -> valor`: hora passada não muda
mais, então uma vez cacheada nunca precisa ser rebuscada — quem decide o que
ainda é elegível para vir do cache é `src/ingest/openmeteo.py`, não este
módulo (aqui só existe leitura/escrita por chave exata).

Se o arquivo estiver ausente, corrompido ou ilegível, o módulo degrada para
cache vazio (loga um warning, nunca levanta exceção) — o cache nunca pode
derrubar uma exportação.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PRECISAO_DECIMAIS = 4  # ~11m no equador; fixo e independente da grade
                        # espacial recalibrada por execução (ver spec).
CAMINHO_PADRAO = Path("data/cache/openmeteo.sqlite")
RETENCAO_DIAS_PADRAO = 35  # cobre JANELA_SERIE_DIAS (30, o maior histórico
                           # pedido hoje) com folga; linhas mais velhas não
                           # servem a nenhum consumidor atual.
LINHAS_PODADAS_PARA_VACUUM = 1000  # abaixo disso o VACUUM custa mais
                                   # (reescreve o arquivo todo) do que o
                                   # espaço que recupera.

Ponto = tuple[float, float]


def _arredondar(ponto: Ponto) -> Ponto:
    lat, lon = ponto
    return (round(lat, PRECISAO_DECIMAIS), round(lon, PRECISAO_DECIMAIS))


class CacheOpenMeteo:
    """Cache thread-safe (lock próprio) sobre um arquivo SQLite."""

    def __init__(
        self, caminho: Path = CAMINHO_PADRAO, retencao_dias: int = RETENCAO_DIAS_PADRAO,
    ) -> None:
        self._caminho = caminho
        self._retencao_dias = retencao_dias
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = self._abrir()

    def _abrir(self) -> sqlite3.Connection | None:
        conn: sqlite3.Connection | None = None
        try:
            self._caminho.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._caminho, check_same_thread=False)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_horario ("
                "lat REAL NOT NULL, lon REAL NOT NULL, variavel TEXT NOT NULL, "
                "data_hora TEXT NOT NULL, valor REAL, buscado_em TEXT NOT NULL, "
                "PRIMARY KEY (lat, lon, variavel, data_hora))"
            )
            conn.commit()
            self._podar(conn)
            return conn
        except (sqlite3.Error, OSError) as exc:
            logger.warning(
                "Falha ao abrir cache Open-Meteo em %s: %s. Operando sem cache.",
                self._caminho, exc,
            )
            if conn is not None:
                # `close()` sobre uma conexão já quebrada pode levantar; este
                # módulo nunca pode levantar (contrato: degrada para cache vazio).
                with suppress(sqlite3.Error):
                    conn.close()
            return None

    def _podar(self, conn: sqlite3.Connection) -> None:
        """Remove linhas mais velhas que `retencao_dias` -- nada hoje pede
        histórico além de JANELA_SERIE_DIAS (30 dias), então o resto é peso
        morto que faria o arquivo crescer sem limite (o arquivo é publicado
        no gh-pages, e o GitHub rejeita push acima de 100MB; ver
        docs/superpowers/specs/2026-08-22-cache-openmeteo-design.md)."""
        corte = (
            datetime.now(timezone.utc) - timedelta(days=self._retencao_dias)
        ).strftime("%Y-%m-%dT%H:%M")
        try:
            cursor = conn.execute("DELETE FROM cache_horario WHERE data_hora < ?", (corte,))
            conn.commit()
            if cursor.rowcount > LINHAS_PODADAS_PARA_VACUUM:
                # VACUUM reescreve o arquivo inteiro (precisa de espaço
                # temporário ~= o tamanho do banco), então não vale a pena
                # com o punhado de linhas que uma execução diária poda; as
                # páginas livres são reaproveitadas na próxima gravação de
                # qualquer forma. Só compensa depois de uma poda grande.
                conn.execute("VACUUM")
        except sqlite3.Error as exc:
            logger.warning("Falha ao podar cache Open-Meteo: %s. Seguindo sem podar.", exc)

    def horas_faltantes(
        self, pontos: list[Ponto], variavel: str, horas: list[str],
    ) -> dict[Ponto, list[str]]:
        """Para cada ponto, quais `horas` (ISO 8601, ex. "2026-08-10T00:00")
        ainda não estão cacheadas para `variavel`."""
        if self._conn is None or not horas:
            return {p: list(horas) for p in pontos} if horas else {}
        placeholders = ",".join("?" * len(horas))
        faltando: dict[Ponto, list[str]] = {}
        with self._lock:
            for ponto in pontos:
                lat, lon = _arredondar(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel = ? AND data_hora IN ({placeholders})",
                        (lat, lon, variavel, *horas),
                    )
                    presentes = {row[0] for row in cursor.fetchall()}
                except sqlite3.Error as exc:
                    logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando ponto como não cacheado.", exc)
                    presentes = set()
                faltantes_ponto = [h for h in horas if h not in presentes]
                if faltantes_ponto:
                    faltando[ponto] = faltantes_ponto
        return faltando

    def ler(
        self, pontos: list[Ponto], variavel: str, horas: list[str],
    ) -> dict[Ponto, dict[str, float | None]]:
        """O que já está cacheado para `pontos`/`variavel`/`horas`."""
        resultado: dict[Ponto, dict[str, float | None]] = {}
        if self._conn is None or not horas:
            return resultado
        placeholders = ",".join("?" * len(horas))
        with self._lock:
            for ponto in pontos:
                lat, lon = _arredondar(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora, valor FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel = ? AND data_hora IN ({placeholders})",
                        (lat, lon, variavel, *horas),
                    )
                    linhas = {row[0]: row[1] for row in cursor.fetchall()}
                except sqlite3.Error as exc:
                    logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando ponto como não cacheado.", exc)
                    linhas = {}
                if linhas:
                    resultado[ponto] = linhas
        return resultado

    def gravar(
        self, registros: list[tuple[Ponto, str, float | None]], variavel: str, buscado_em: str,
    ) -> None:
        """Upsert em lote: cada item é `(ponto, data_hora, valor)`."""
        if self._conn is None or not registros:
            return
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT INTO cache_horario (lat, lon, variavel, data_hora, valor, buscado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (lat, lon, variavel, data_hora) DO UPDATE SET "
                    "valor = excluded.valor, buscado_em = excluded.buscado_em",
                    [
                        (*_arredondar(ponto), variavel, hora, valor, buscado_em)
                        for ponto, hora, valor in registros
                    ],
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                logger.warning(
                    "Falha ao gravar no cache Open-Meteo: %s. Dado desta execução não foi persistido.", exc,
                )
