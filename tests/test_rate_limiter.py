import threading
import time

from src.ingest.rate_limiter import RateLimiter


class RelogioFalso:
    """Relógio controlável: `dormir` avança o próprio relógio, sem esperar de verdade."""

    def __init__(self) -> None:
        self.agora = 0.0

    def tempo(self) -> float:
        return self.agora

    def dormir(self, segundos: float) -> None:
        self.agora += segundos


def _limiter(max_por_minuto: int = 600, max_por_hora: int = 5000) -> tuple[RateLimiter, RelogioFalso]:
    relogio = RelogioFalso()
    limiter = RateLimiter(
        max_por_minuto=max_por_minuto,
        max_por_hora=max_por_hora,
        relogio=relogio.tempo,
        dormir=relogio.dormir,
    )
    return limiter, relogio


def test_acquire_nao_bloqueia_abaixo_do_limite():
    limiter, relogio = _limiter(max_por_minuto=2, max_por_hora=100)

    limiter.acquire()
    limiter.acquire()

    assert relogio.agora == 0.0


def test_acquire_bloqueia_ate_a_janela_de_minuto_abrir():
    limiter, relogio = _limiter(max_por_minuto=2, max_por_hora=100)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert relogio.agora == 60.0


def test_acquire_respeita_teto_por_hora_mesmo_com_folga_no_minuto():
    limiter, relogio = _limiter(max_por_minuto=100, max_por_hora=2)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert relogio.agora == 3600.0


def test_acquire_nao_bloqueia_depois_que_a_janela_desliza():
    limiter, relogio = _limiter(max_por_minuto=1, max_por_hora=100)

    limiter.acquire()
    relogio.agora = 61.0
    limiter.acquire()

    assert relogio.agora == 61.0


def test_acquire_e_thread_safe_sob_concorrencia_real():
    limiter = RateLimiter(max_por_minuto=1000, max_por_hora=100000, relogio=time.monotonic, dormir=time.sleep)
    contagens: list[int] = []
    lock = threading.Lock()

    def registrar() -> None:
        limiter.acquire()
        with lock:
            contagens.append(1)

    threads = [threading.Thread(target=registrar) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert sum(contagens) == 50
