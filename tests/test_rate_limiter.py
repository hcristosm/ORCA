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


def test_acquire_espaca_requisicoes_com_intervalo_minimo():
    relogio = RelogioFalso()
    limiter = RateLimiter(
        max_por_minuto=1000, max_por_hora=100000, intervalo_minimo_segundos=5.0,
        relogio=relogio.tempo, dormir=relogio.dormir,
    )

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert relogio.agora == 10.0


def test_acquire_intervalo_minimo_nao_bloqueia_quando_zero():
    limiter, relogio = _limiter(max_por_minuto=1000, max_por_hora=100000)

    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert relogio.agora == 0.0


def test_acquire_intervalo_minimo_evita_rajadas_sob_concorrencia_real():
    """Reproduz o bug: threads liberadas ao mesmo tempo pela janela de contagem
    não devem poder disparar a requisição no mesmo instante — precisa haver
    espaçamento mínimo real entre elas, não só um teto de contagem por janela.
    """
    limiter = RateLimiter(
        max_por_minuto=1000, max_por_hora=100000, intervalo_minimo_segundos=0.05,
        relogio=time.monotonic, dormir=time.sleep,
    )
    instantes: list[float] = []
    lock = threading.Lock()

    def registrar() -> None:
        limiter.acquire()
        with lock:
            instantes.append(time.monotonic())

    threads = [threading.Thread(target=registrar) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    instantes.sort()
    intervalos = [b - a for a, b in zip(instantes, instantes[1:])]
    assert all(intervalo >= 0.045 for intervalo in intervalos)


def test_max_concorrentes_limita_requisicoes_em_voo_simultaneas():
    """Reproduz o bug real: espaçar o início das requisições não basta, porque
    uma requisição pode ficar em voo por segundos. `max_concorrentes` precisa
    limitar quantas ficam abertas ao mesmo tempo, não só a taxa de início.
    """
    limiter = RateLimiter(
        max_por_minuto=100000, max_por_hora=100000, max_concorrentes=2,
        relogio=time.monotonic, dormir=time.sleep,
    )
    em_voo = 0
    pico = 0
    lock = threading.Lock()

    def tarefa() -> None:
        nonlocal em_voo, pico
        limiter.acquire()
        try:
            with lock:
                em_voo += 1
                pico = max(pico, em_voo)
            time.sleep(0.05)
            with lock:
                em_voo -= 1
        finally:
            limiter.release()

    threads = [threading.Thread(target=tarefa) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert pico <= 2


def test_max_concorrentes_none_nao_limita_concorrencia():
    limiter, relogio = _limiter(max_por_minuto=1000, max_por_hora=100000)

    limiter.acquire()
    limiter.acquire()
    limiter.release()
    limiter.release()

    assert relogio.agora == 0.0


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
