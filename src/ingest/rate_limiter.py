"""Limitador de taxa thread-safe para chamadas à Open-Meteo.

Janela deslizante (por minuto e por hora) sobre uma única lista de
timestamps: `acquire()` bloqueia a thread chamadora até que uma nova
requisição caiba nos dois tetos ao mesmo tempo. Usado para permitir
paralelizar as chamadas HTTP (por lote e por UF) sem estourar os limites
documentados da API — ver `src/ingest/openmeteo.py` e
`src/export/nacional.py`.

`intervalo_minimo_segundos` cobre um problema diferente do teto por janela:
quando várias threads chegam liberadas ao mesmo tempo (ex.: todas bem abaixo
do teto por minuto), nada as impede de disparar a requisição no mesmo
instante. Em produção (exportação nacional de 21/08/2026) isso causou
rajadas de até ~20 requisições simultâneas (4 UFs × 5 lotes) que a
Open-Meteo respondia com 429/timeout em cadeia, mesmo a taxa agregada
estando bem abaixo de 500/min — 8 das 27 UFs esgotaram os retries e ficaram
de fora do dashboard. `acquire()` então também espaça cada concessão de
`intervalo_minimo_segundos` em relação à anterior, suavizando a rajada em
vez de só limitar a contagem total na janela.
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
        intervalo_minimo_segundos: float = 0.0,
        relogio=time.monotonic,
        dormir=time.sleep,
    ) -> None:
        self._max_por_minuto = max_por_minuto
        self._max_por_hora = max_por_hora
        self._intervalo_minimo_segundos = intervalo_minimo_segundos
        self._relogio = relogio
        self._dormir = dormir
        self._timestamps: deque[float] = deque()
        self._ultima_concessao: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Bloqueia até que uma nova requisição caiba nos dois tetos e no
        espaçamento mínimo em relação à última concedida, depois a registra."""
        while True:
            with self._lock:
                agora = self._relogio()
                self._purgar(agora)
                espera = self._espera_necessaria(agora)
                if espera <= 0:
                    self._timestamps.append(agora)
                    self._ultima_concessao = agora
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
        if self._ultima_concessao is not None:
            espera = max(espera, self._intervalo_minimo_segundos - (agora - self._ultima_concessao))
        return espera
