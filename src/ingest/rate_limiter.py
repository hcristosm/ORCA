"""Limitador de taxa thread-safe para chamadas à Open-Meteo.

Janela deslizante (por minuto e por hora) sobre uma única lista de
timestamps: `acquire()` bloqueia a thread chamadora até que uma nova
requisição caiba nos dois tetos ao mesmo tempo. Usado para permitir
paralelizar as chamadas HTTP (por lote e por UF) sem estourar os limites
documentados da API — ver `src/ingest/openmeteo.py` e
`src/export/nacional.py`.
"""

from __future__ import annotations

import threading
import time
from collections import deque

JANELA_MINUTO_SEGUNDOS = 60.0
JANELA_HORA_SEGUNDOS = 3600.0


class RateLimiter:
    """Limita requisições/minuto e requisições/hora com janela deslizante."""

    def __init__(
        self,
        max_por_minuto: int,
        max_por_hora: int,
        relogio=time.monotonic,
        dormir=time.sleep,
    ) -> None:
        self._max_por_minuto = max_por_minuto
        self._max_por_hora = max_por_hora
        self._relogio = relogio
        self._dormir = dormir
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Bloqueia até que uma nova requisição caiba nos dois tetos, depois a registra."""
        while True:
            with self._lock:
                agora = self._relogio()
                self._purgar(agora)
                espera = self._espera_necessaria(agora)
                if espera <= 0:
                    self._timestamps.append(agora)
                    return
            self._dormir(espera)

    def _purgar(self, agora: float) -> None:
        limite = agora - JANELA_HORA_SEGUNDOS
        while self._timestamps and self._timestamps[0] <= limite:
            self._timestamps.popleft()

    def _espera_necessaria(self, agora: float) -> float:
        recentes_minuto = [t for t in self._timestamps if t > agora - JANELA_MINUTO_SEGUNDOS]
        espera = 0.0
        if len(recentes_minuto) >= self._max_por_minuto:
            espera = max(espera, JANELA_MINUTO_SEGUNDOS - (agora - recentes_minuto[0]))
        if len(self._timestamps) >= self._max_por_hora:
            espera = max(espera, JANELA_HORA_SEGUNDOS - (agora - self._timestamps[0]))
        return espera
