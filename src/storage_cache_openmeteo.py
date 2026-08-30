"""Cache local incremental para respostas horárias da Open-Meteo.

Uma tabela
SQLite `(lat, lon, variavel, data_hora) -> valor`: hora passada não muda
mais, então uma vez cacheada nunca precisa ser rebuscada — quem decide o que
ainda é elegível para vir do cache é `src/ingest/openmeteo.py`, não este
módulo (aqui só existe leitura/escrita por chave exata).

Armazenamento interno é compacto (`WITHOUT ROWID`, coordenadas/datas como
inteiro, variável normalizada numa tabela auxiliar) porque o volume real de
produção (cobertura nacional, ~2,4 milhões de linhas na primeira população)
faz o schema "óbvio" (tudo TEXT, rowid implícito) passar de 300MB -- acima
do limite que o workflow aceita publicar no gh-pages. A interface pública
(strings ISO, floats) não muda; só a codificação em disco.

Se o arquivo estiver ausente, corrompido ou ilegível, o módulo degrada para
cache vazio (loga um warning, nunca levanta exceção) — o cache nunca pode
derrubar uma exportação.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

PRECISAO_DECIMAIS = 4  # ~11m no equador; fixo e independente da grade
                        # espacial recalibrada por execução (ver spec).
ESCALA_COORDENADA = 10 ** PRECISAO_DECIMAIS
CAMINHO_PADRAO = Path("data/cache/openmeteo.sqlite")
RETENCAO_DIAS_PADRAO = 35  # cobre JANELA_SERIE_DIAS (30, o maior histórico
                           # pedido hoje) com folga; linhas mais velhas não
                           # servem a nenhum consumidor atual.
LINHAS_PODADAS_PARA_VACUUM = 1000  # abaixo disso o VACUUM custa mais
                                   # (reescreve o arquivo todo) do que o
                                   # espaço que recupera.

Ponto = tuple[float, float]


def _lat_lon_inteiros(ponto: Ponto) -> tuple[int, int]:
    lat, lon = ponto
    return (round(lat * ESCALA_COORDENADA), round(lon * ESCALA_COORDENADA))


def _hora_para_epoch(hora: str) -> int:
    dt = datetime.strptime(hora, "%Y-%m-%dT%H:%M").replace(tzinfo=UTC)
    return int(dt.timestamp()) // 3600


def _epoch_para_hora(epoch: int) -> str:
    dt = datetime.fromtimestamp(epoch * 3600, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _buscado_em_para_epoch_dia(buscado_em: str) -> int:
    dt = datetime.fromisoformat(buscado_em)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp()) // 86400


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
                "CREATE TABLE IF NOT EXISTS variaveis ("
                "id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS cache_horario ("
                "lat INTEGER NOT NULL, lon INTEGER NOT NULL, variavel_id INTEGER NOT NULL, "
                "data_hora INTEGER NOT NULL, valor REAL, buscado_em INTEGER NOT NULL, "
                "PRIMARY KEY (lat, lon, variavel_id, data_hora)) WITHOUT ROWID"
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

    def _variavel_id(self, conn: sqlite3.Connection, nome: str, criar: bool) -> int | None:
        cursor = conn.execute("SELECT id FROM variaveis WHERE nome = ?", (nome,))
        row = cursor.fetchone()
        if row is not None:
            return row[0]
        if not criar:
            return None
        cursor = conn.execute("INSERT INTO variaveis (nome) VALUES (?)", (nome,))
        conn.commit()
        return cursor.lastrowid

    def _podar(self, conn: sqlite3.Connection) -> None:
        """Remove linhas mais velhas que `retencao_dias` -- nada hoje pede
        histórico além de JANELA_SERIE_DIAS (30 dias), então o resto é peso
        morto que faria o arquivo crescer sem limite (o arquivo é publicado
        no gh-pages, e o GitHub rejeita push acima de 100MB)."""
        corte_epoch = _hora_para_epoch(
            (datetime.now(UTC) - timedelta(days=self._retencao_dias)).strftime("%Y-%m-%dT%H:%M")
        )
        try:
            cursor = conn.execute("DELETE FROM cache_horario WHERE data_hora < ?", (corte_epoch,))
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
        horas_epoch = [_hora_para_epoch(h) for h in horas]
        faltando: dict[Ponto, list[str]] = {}
        with self._lock:
            try:
                variavel_id = self._variavel_id(self._conn, variavel, criar=False)
            except sqlite3.Error as exc:
                logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando como não cacheado.", exc)
                return {p: list(horas) for p in pontos}
            if variavel_id is None:
                return {p: list(horas) for p in pontos}
            placeholders = ",".join("?" * len(horas_epoch))
            for ponto in pontos:
                lat, lon = _lat_lon_inteiros(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel_id = ? AND data_hora IN ({placeholders})",  # nosec B608 - placeholders é só "?,?,...", valores vão parametrizados abaixo
                        (lat, lon, variavel_id, *horas_epoch),
                    )
                    presentes = {row[0] for row in cursor.fetchall()}
                except sqlite3.Error as exc:
                    logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando ponto como não cacheado.", exc)
                    presentes = set()
                faltantes_ponto = [
                    h for h, h_epoch in zip(horas, horas_epoch) if h_epoch not in presentes
                ]
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
        horas_epoch = [_hora_para_epoch(h) for h in horas]
        with self._lock:
            try:
                variavel_id = self._variavel_id(self._conn, variavel, criar=False)
            except sqlite3.Error as exc:
                logger.warning("Falha ao ler cache Open-Meteo: %s. Tratando como não cacheado.", exc)
                return resultado
            if variavel_id is None:
                return resultado
            placeholders = ",".join("?" * len(horas_epoch))
            for ponto in pontos:
                lat, lon = _lat_lon_inteiros(ponto)
                try:
                    cursor = self._conn.execute(
                        f"SELECT data_hora, valor FROM cache_horario WHERE lat = ? AND lon = ? "
                        f"AND variavel_id = ? AND data_hora IN ({placeholders})",  # nosec B608 - placeholders é só "?,?,...", valores vão parametrizados abaixo
                        (lat, lon, variavel_id, *horas_epoch),
                    )
                    linhas = {_epoch_para_hora(row[0]): row[1] for row in cursor.fetchall()}
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
                variavel_id = self._variavel_id(self._conn, variavel, criar=True)
                buscado_em_dia = _buscado_em_para_epoch_dia(buscado_em)
                self._conn.executemany(
                    "INSERT INTO cache_horario (lat, lon, variavel_id, data_hora, valor, buscado_em) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT (lat, lon, variavel_id, data_hora) DO UPDATE SET "
                    "valor = excluded.valor, buscado_em = excluded.buscado_em",
                    [
                        (*_lat_lon_inteiros(ponto), variavel_id, _hora_para_epoch(hora), valor, buscado_em_dia)
                        for ponto, hora, valor in registros
                    ],
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                logger.warning(
                    "Falha ao gravar no cache Open-Meteo: %s. Dado desta execução não foi persistido.", exc,
                )
