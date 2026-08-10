# Ingestão incremental do INMET Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar `src/ingest/inmet.py` incremental: pular o download do ZIP quando ele não mudou (GET condicional via ETag) e reprocessar localmente só as estações cujo CRC32 mudou, mesclando apenas os últimos dias em vez de reparsear o ano inteiro a cada execução.

**Architecture:** Um manifesto JSON por UF/ano (`data/inmet_manifest_<uf>_<ano>.json`) guarda o ETag do último ZIP baixado e o CRC32 + última leitura de cada estação. `ingerir_uf` usa esse manifesto para decidir, por estação, se reaproveita as linhas já salvas no CSV acumulado (`data/chuva_<uf>_<ano>.csv`) ou se reparseia e mescla só a janela de retificação (7 dias) mais recente. Nenhuma mudança na interface pública consumida por CLI/dashboard.

**Tech Stack:** Python 3.11+, `requests` (GET condicional via `If-None-Match`/ETag), `zipfile` (CRC32 sem descompactar), `json` (manifesto), `pandas` (merge/dedupe), `pytest` + `responses` (testes com HTTP mockado).

## Global Constraints

- `ingerir_uf(uf, ano, diretorio_dados, timeout=120.0, max_retries=3)` mantém exatamente a mesma assinatura pública e o mesmo comportamento externo — `python -m src.cli ingest-inmet --uf SP --ano 2026` continua funcionando idêntico do ponto de vista de quem chama.
- Não existe download parcial por data do servidor do INMET (confirmado por `HEAD` real: `Accept-Ranges`/`ETag` suportados, mas cada estação tem um único arquivo cobrindo o ano inteiro). A otimização é inteiramente local: GET condicional do ZIP inteiro (pula a transferência se não mudou) + CRC32 por estação (pula o reprocessamento se não mudou).
- Estado rastreado em `data/inmet_manifest_<uf>_<ano>.json` — não reaproveita `ultima_atualizacao.txt` (proposito diferente, sem granularidade por estação) nem infere tudo do CSV de saída (não guarda CRC do ZIP).
- Janela de retificação: 7 dias (168h) a partir da última leitura já salva da estação. Dentro dessa janela, o valor mais recente baixado prevalece em caso de retificação (mesmo `data_hora`, `chuva_mm` diferente). Fora da janela, os dados já salvos são tratados como estáveis — limitação documentada, não garantia do INMET.
- Todo teste novo usa HTTP mockado (`responses`), sem depender de rede — mesmo padrão dos testes já existentes em `tests/test_inmet.py`.

---

### Task 1: GET condicional do ZIP + CRC32 por estação + manifesto

**Files:**
- Modify: `src/config.py` (adicionar `caminho_manifesto_inmet`)
- Modify: `src/ingest/inmet.py` (novo `baixar_zip_ano_condicional` substituindo `baixar_zip_ano`; `_crc32_estacao`; `_carregar_manifesto`/`_salvar_manifesto`; `ler_serie_estacao` refatorado para reusar `_nome_arquivo_no_zip`)
- Modify: `tests/test_inmet.py` (substitui os 2 testes de `baixar_zip_ano` por equivalentes de `baixar_zip_ano_condicional`, adiciona os novos)

**Interfaces:**
- Produces: `caminho_manifesto_inmet(uf, ano, data_dir=DATA_DIR) -> Path`; `baixar_zip_ano_condicional(ano, destino, etag_anterior, timeout=120.0, max_retries=3, backoff_factor=2.0, session=None) -> tuple[Path, str | None]`; `_crc32_estacao(zip_path, uf, codigo) -> int | None`; `_carregar_manifesto(caminho) -> dict` (formato `{"etag_zip": str | None, "estacoes": {codigo: {"crc32": int, "ultima_data_hora": str}}}`); `_salvar_manifesto(caminho, manifesto) -> None`. Usados por Task 2 (`ingerir_uf`).
- Removes: `baixar_zip_ano` (substituída por `baixar_zip_ano_condicional`, que cobre o mesmo caso — `etag_anterior=None` baixa sempre, igual ao comportamento antigo).

- [ ] **Step 1: Adicionar `caminho_manifesto_inmet` em `src/config.py`**

Adicionar logo após `caminho_zip_inmet` (última função do arquivo):

```python
def caminho_manifesto_inmet(uf: str, ano: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"inmet_manifest_{uf.lower()}_{ano}.json"
```

- [ ] **Step 2: Adicionar `import json` em `src/ingest/inmet.py`**

No topo do arquivo, junto aos outros imports da stdlib (ordem alfabética com os já existentes: `csv, io, json, logging, time, zipfile`):

```python
import csv
import io
import json
import logging
import time
import zipfile
```

- [ ] **Step 3: Generalizar `_get_com_retry` para aceitar cabeçalhos extras**

Substituir a assinatura e a primeira linha do corpo de `_get_com_retry`:

```python
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
```

(`headers_extra=None` é o padrão — chamadas existentes como `fetch_estacoes` não mudam de comportamento.)

- [ ] **Step 4: Substituir `baixar_zip_ano` por `baixar_zip_ano_condicional`**

Remover a função `baixar_zip_ano` inteira (do `def baixar_zip_ano(` até o `raise` final dela) e colocar no lugar:

```python
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
    headers_extra = {"If-None-Match": etag_anterior} if etag_anterior else None

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
```

- [ ] **Step 5: Refatorar `ler_serie_estacao` e adicionar `_nome_arquivo_no_zip` / `_crc32_estacao`**

Substituir a função `ler_serie_estacao` atual (que hoje faz a busca do nome do arquivo inline) por:

```python
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
```

- [ ] **Step 6: Adicionar `_carregar_manifesto`/`_salvar_manifesto`**

Logo após `_crc32_estacao`/`ler_serie_estacao` (antes de `ingerir_uf`):

```python
def _carregar_manifesto(caminho: Path) -> dict:
    if not caminho.exists():
        return {"etag_zip": None, "estacoes": {}}
    return json.loads(caminho.read_text())


def _salvar_manifesto(caminho: Path, manifesto: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False))
```

- [ ] **Step 7: Atualizar o import de `src.config` em `src/ingest/inmet.py`**

Trocar:

```python
from src.config import caminho_chuva, caminho_zip_inmet
from src.storage import salvar_chuva
```

Por:

```python
from src.config import caminho_chuva, caminho_manifesto_inmet, caminho_zip_inmet
from src.storage import ler_chuva, salvar_chuva
```

(`ler_chuva` será usado pelo `ingerir_uf` reescrito na Task 2 — importar já agora evita um diff extra depois.)

- [ ] **Step 8: Atualizar `tests/test_inmet.py` — trocar import e os 2 testes de `baixar_zip_ano`**

Trocar o bloco de import no topo do arquivo:

```python
from src.ingest.inmet import (
    ESTACOES_URL,
    INMETFetchError,
    _parse_csv_estacao,
    baixar_zip_ano,
    fetch_estacoes,
    ler_serie_estacao,
)
```

Por:

```python
from src.ingest.inmet import (
    ESTACOES_URL,
    INMETFetchError,
    _carregar_manifesto,
    _crc32_estacao,
    _parse_csv_estacao,
    _salvar_manifesto,
    baixar_zip_ano_condicional,
    fetch_estacoes,
    ler_serie_estacao,
)
```

Substituir os dois testes `test_baixar_zip_ano_usa_cache_quando_download_falha` e `test_baixar_zip_ano_sem_cache_levanta_erro` por:

```python
@responses.activate
def test_baixar_zip_ano_condicional_baixa_e_retorna_etag(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    responses.add(
        responses.GET,
        "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip",
        body=b"conteudo do zip",
        status=200,
        headers={"ETag": '"abc123"'},
    )

    caminho, etag = baixar_zip_ano_condicional(2026, destino, etag_anterior=None)

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo do zip"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_reaproveita_cache_em_304(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    destino.write_bytes(b"conteudo em cache")

    responses.add(
        responses.GET,
        "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip",
        status=304,
    )

    caminho, etag = baixar_zip_ano_condicional(2026, destino, etag_anterior='"abc123"')

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo em cache"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_usa_cache_quando_download_falha(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"
    destino.write_bytes(b"conteudo em cache")

    responses.add(responses.GET, "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip", status=500)

    caminho, etag = baixar_zip_ano_condicional(
        2026, destino, etag_anterior='"abc123"', max_retries=1, backoff_factor=0.01
    )

    assert caminho == destino
    assert destino.read_bytes() == b"conteudo em cache"
    assert etag == '"abc123"'


@responses.activate
def test_baixar_zip_ano_condicional_sem_cache_levanta_erro(tmp_path: Path):
    destino = tmp_path / "inmet_2026.zip"

    responses.add(responses.GET, "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip", status=500)

    with pytest.raises(INMETFetchError):
        baixar_zip_ano_condicional(2026, destino, etag_anterior=None, max_retries=1, backoff_factor=0.01)
```

Adicionar ao final do arquivo:

```python
def test_crc32_estacao_retorna_crc_sem_descompactar(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    crc = _crc32_estacao(zip_path, "SP", "A701")

    with zipfile.ZipFile(zip_path) as zf:
        crc_esperado = zf.getinfo(zf.namelist()[0]).CRC
    assert crc == crc_esperado


def test_crc32_estacao_retorna_none_se_estacao_nao_existe(tmp_path: Path):
    nome = "INMET_SE_SP_A701_SAO PAULO - MIRANTE_01-01-2026_A_31-07-2026.CSV"
    zip_path = _zip_com_estacao(tmp_path, nome, CSV_ESTACAO_EXEMPLO)

    assert _crc32_estacao(zip_path, "SP", "A999") is None


def test_manifesto_salvar_e_carregar_round_trip(tmp_path: Path):
    caminho = tmp_path / "inmet_manifest_sp_2026.json"
    manifesto = {
        "etag_zip": '"abc123"',
        "estacoes": {"A701": {"crc32": 999, "ultima_data_hora": "2026-08-05T23:00:00+00:00"}},
    }

    _salvar_manifesto(caminho, manifesto)
    carregado = _carregar_manifesto(caminho)

    assert carregado == manifesto


def test_manifesto_carregar_arquivo_inexistente_retorna_vazio(tmp_path: Path):
    caminho = tmp_path / "nao_existe.json"

    assert _carregar_manifesto(caminho) == {"etag_zip": None, "estacoes": {}}
```

- [ ] **Step 9: Rodar os testes de `test_inmet.py`**

Run: `pytest tests/test_inmet.py -v`
Expected: 13 passed (7 testes pré-existentes que não mudam: `test_parse_csv_estacao_le_datas_e_chuva`, `test_parse_csv_estacao_trata_valor_ausente_como_nan`, `test_ler_serie_estacao_encontra_arquivo_por_uf_e_codigo`, `test_ler_serie_estacao_levanta_erro_se_estacao_nao_existe`, `test_fetch_estacoes_filtra_por_uf` + 4 novos de `baixar_zip_ano_condicional` + 4 novos de CRC32/manifesto = 13), 0 falhas.

- [ ] **Step 10: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 47 passed (41 antes desta task − 2 testes removidos de `baixar_zip_ano` + 8 novos = 47), 0 falhas.

- [ ] **Step 11: Commit**

```bash
git add src/config.py src/ingest/inmet.py tests/test_inmet.py
git commit -m "feat(ingest/inmet): conditional ZIP download and per-station CRC32 manifest"
```

---

### Task 2: `ingerir_uf` incremental (merge por estação, janela de retificação)

**Files:**
- Modify: `src/ingest/inmet.py` (reescreve `ingerir_uf`, adiciona `JANELA_RETIFICACAO`, atualiza docstring do módulo)
- Modify: `tests/test_inmet.py` (adiciona os 3 testes fim a fim)

**Interfaces:**
- Consumes: `caminho_manifesto_inmet`, `baixar_zip_ano_condicional`, `_crc32_estacao`, `_carregar_manifesto`, `_salvar_manifesto`, `ler_chuva` (todos de Task 1).
- Produces: `ingerir_uf(uf, ano, diretorio_dados, timeout=120.0, max_retries=3) -> pd.DataFrame` — mesma assinatura e schema de saída de antes (`data_hora, chuva_mm, codigo_estacao, nome_estacao, uf, latitude, longitude`), comportamento incremental internamente.

- [ ] **Step 1: Adicionar `JANELA_RETIFICACAO` e atualizar a docstring do módulo**

Adicionar a constante logo antes de `ingerir_uf`:

```python
JANELA_RETIFICACAO = pd.Timedelta(days=7)
```

No topo do arquivo, adicionar um parágrafo à docstring do módulo (depois do parágrafo que termina em "...documentado no README como limitação conhecida." e antes do parágrafo sobre `/estacoes/T`):

```python
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
```

- [ ] **Step 2: Reescrever `ingerir_uf`**

Substituir a função `ingerir_uf` inteira por:

```python
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
    existente = ler_chuva(saida) if saida.exists() else None
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
            serie_final = serie_existente_estacao
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
                ultima_existente = serie_existente_estacao["data_hora"].max()
                cutoff = ultima_existente - JANELA_RETIFICACAO
                antigas_estaveis = serie_existente_estacao[serie_existente_estacao["data_hora"] < cutoff]
                recentes_novas = serie_nova[serie_nova["data_hora"] >= cutoff]
                serie_final = (
                    pd.concat([antigas_estaveis, recentes_novas], ignore_index=True)
                    .drop_duplicates(subset="data_hora", keep="last")
                    .sort_values("data_hora")
                    .reset_index(drop=True)
                )

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
```

- [ ] **Step 3: Adicionar um helper de CSV multi-linha e os 3 testes fim a fim em `tests/test_inmet.py`**

Adicionar `import zipfile` já está no topo do arquivo; adicionar também, junto às outras funções auxiliares do arquivo (perto de `_zip_com_estacao`):

```python
def _csv_estacao(codigo: str, leituras: list[tuple[str, str, str]]) -> bytes:
    """Monta um CSV horário do INMET com as linhas de dado informadas (data, hora 'HHMM', precip)."""
    linhas_dados = "".join(f"{data};{hora} UTC;{precip};999\r\n" for data, hora, precip in leituras)
    return (
        "REGIAO:;SE\r\nUF:;SP\r\nESTACAO:;TESTE\r\n"
        f"CODIGO (WMO):;{codigo}\r\nLATITUDE:;-23,5\r\nLONGITUDE:;-46,6\r\n"
        "ALTITUDE:;800\r\nDATA DE FUNDACAO:;01/01/00\r\n"
        "Data;Hora UTC;PRECIPITACAO TOTAL, HORARIO (mm);OUTRA COLUNA\r\n"
        f"{linhas_dados}"
    ).encode("latin-1")


def _bytes_zip(conteudos: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nome, conteudo in conteudos.items():
            zf.writestr(nome, conteudo)
    return buf.getvalue()


def _mock_estacoes(*codigos: str) -> list[dict]:
    return [
        {
            "CD_ESTACAO": codigo, "DC_NOME": f"ESTACAO {codigo}", "SG_ESTADO": "SP",
            "VL_LATITUDE": "-23.5", "VL_LONGITUDE": "-46.6", "CD_SITUACAO": "Operante",
        }
        for codigo in codigos
    ]


_NOME_ZIP_URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/2026.zip"


def _nome_no_zip(codigo: str) -> str:
    return f"INMET_SE_SP_{codigo}_ESTACAO {codigo}_01-01-2026_A_09-08-2026.CSV"
```

Adicionar ao final do arquivo:

```python
@responses.activate
def test_ingerir_uf_primeira_execucao_processa_todas_as_estacoes(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    zip_v1 = _bytes_zip({
        _nome_no_zip("A701"): _csv_estacao("A701", [
            ("2026/08/01", "0000", "1,0"),
            ("2026/08/01", "0100", "2,0"),
        ]),
    })
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    resultado = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert len(resultado) == 2
    assert set(resultado["codigo_estacao"]) == {"A701"}


@responses.activate
def test_ingerir_uf_segunda_execucao_pula_estacao_sem_mudanca_e_mescla_a_que_mudou(
    tmp_path: Path, monkeypatch
):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701", "B002"), status=200)
    csv_a701 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0"), ("2026/08/01", "0100", "2,0")])
    csv_b002_v1 = _csv_estacao("B002", [("2026/08/01", "0000", "5,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_a701, _nome_no_zip("B002"): csv_b002_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    primeira = ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    assert len(primeira) == 3

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701", "B002"), status=200)
    csv_b002_v2 = _csv_estacao(
        "B002", [("2026/08/01", "0000", "5,0"), ("2026/08/01", "0200", "7,0")]
    )
    zip_v2 = _bytes_zip({_nome_no_zip("A701"): csv_a701, _nome_no_zip("B002"): csv_b002_v2})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v2, status=200, headers={"ETag": '"v2"'})

    chamadas_a701 = []
    original_ler_serie = ler_serie_estacao

    def _espiao(zip_path, uf, codigo):
        if codigo == "A701":
            chamadas_a701.append(codigo)
        return original_ler_serie(zip_path, uf, codigo)

    monkeypatch.setattr("src.ingest.inmet.ler_serie_estacao", _espiao)

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    assert chamadas_a701 == []
    assert len(segunda[segunda["codigo_estacao"] == "A701"]) == 2
    assert len(segunda[segunda["codigo_estacao"] == "B002"]) == 2


@responses.activate
def test_ingerir_uf_retificacao_dentro_da_janela_usa_valor_mais_novo(tmp_path: Path):
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v1 = _csv_estacao("A701", [("2026/08/01", "0000", "1,0")])
    zip_v1 = _bytes_zip({_nome_no_zip("A701"): csv_v1})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v1, status=200, headers={"ETag": '"v1"'})

    primeira = ingerir_uf("SP", 2026, tmp_path, max_retries=1)
    assert primeira[primeira["codigo_estacao"] == "A701"]["chuva_mm"].iloc[0] == 1.0

    responses.reset()
    responses.add(responses.GET, ESTACOES_URL, json=_mock_estacoes("A701"), status=200)
    csv_v2 = _csv_estacao("A701", [("2026/08/01", "0000", "9,9")])
    zip_v2 = _bytes_zip({_nome_no_zip("A701"): csv_v2})
    responses.add(responses.GET, _NOME_ZIP_URL, body=zip_v2, status=200, headers={"ETag": '"v2"'})

    segunda = ingerir_uf("SP", 2026, tmp_path, max_retries=1)

    linha = segunda[segunda["codigo_estacao"] == "A701"]
    assert len(linha) == 1
    assert linha["chuva_mm"].iloc[0] == 9.9
```

- [ ] **Step 4: Rodar os testes de `test_inmet.py`**

Run: `pytest tests/test_inmet.py -v`
Expected: 16 passed (13 do Task 1 + 3 novos), 0 falhas.

- [ ] **Step 5: Rodar a suíte completa para checar regressão**

Run: `pytest -q`
Expected: 50 passed (47 do Task 1 + 3 novos), 0 falhas.

- [ ] **Step 6: Commit**

```bash
git add src/ingest/inmet.py tests/test_inmet.py
git commit -m "feat(ingest/inmet): incremental merge per station with 7-day rectification window"
```

---

### Task 3: Atualizar README

**Files:**
- Modify: `README.md`

**Interfaces:**
- Nenhuma — só texto.

- [ ] **Step 1: Remover o item do Roadmap**

Trocar:

```markdown
- Fallback municipal: camadas próprias de prefeituras em ArcGIS REST, sem
  reescrever o pipeline de ingestão.
- Cobrir mais UFs além de SP.
- Persistir o histórico de chuva incrementalmente (hoje cada ingestão baixa o
  ano inteiro de novo).
```

Por:

```markdown
- Fallback municipal: camadas próprias de prefeituras em ArcGIS REST, sem
  reescrever o pipeline de ingestão.
- Cobrir mais UFs além de SP.
```

- [ ] **Step 2: Atualizar "Limitações conhecidas"**

Trocar o primeiro bullet:

```markdown
- **A chuva do INMET tem alguns dias de defasagem.** O pacote histórico anual
  não é atualizado minuto a minuto; a "chuva acumulada" mostrada no dashboard
  é sempre relativa à leitura mais recente **disponível**, não necessariamente
  a "agora". O próprio dashboard mostra essa data de referência.
```

Por:

```markdown
- **A chuva do INMET tem alguns dias de defasagem.** O pacote histórico anual
  não é atualizado minuto a minuto; a "chuva acumulada" mostrada no dashboard
  é sempre relativa à leitura mais recente **disponível**, não necessariamente
  a "agora". O próprio dashboard mostra essa data de referência.
- **A ingestão do INMET é incremental, não por data no servidor.** O INMET só
  oferece o ZIP anual completo — não há como baixar só um intervalo de datas
  do servidor (confirmado por `HEAD` real: `Range`/`ETag` suportados, mas
  cada estação tem um único arquivo cobrindo o ano inteiro). A partir da
  segunda execução, o download pula quando o ZIP não mudou (GET condicional)
  e o reprocessamento local pula estações sem mudança via CRC32, mesclando
  só os últimos 7 dias das que mudaram (janela de retificação). Retificações
  do INMET fora dessa janela de 7 dias não são recapturadas — ver
  `src/ingest/inmet.py` e
  [o spec da ingestão incremental](docs/superpowers/specs/2026-08-09-ingestao-inmet-incremental-design.md).
```

- [ ] **Step 3: Atualizar "Testes e CI"**

Trocar:

```markdown
36 testes cobrindo: parsing de resposta ArcGIS REST (CPRM/SGB), paginação,
retry com backoff e fallback para cache local; parsing do CSV do INMET e
leitura de estação dentro do ZIP anual; parsing do XML/SOAP da ANA, retry em
HTTP 429 e o filtro de estações sem dado recente; a lógica de cruzamento
espacial (estação mais próxima, incluindo o pareamento combinado INMET+ANA
com desempate por recência) e temporal (chuva acumulada 24h/72h); e as
funções auxiliares do dashboard. Toda chamada de rede é mockada, então a
suíte roda sem internet.
```

Por:

```markdown
50 testes cobrindo: parsing de resposta ArcGIS REST (CPRM/SGB), paginação,
retry com backoff e fallback para cache local; parsing do CSV do INMET,
leitura de estação dentro do ZIP anual, GET condicional do ZIP (ETag/304) e
a ingestão incremental por CRC32 (estação sem mudança pulada, estação
mudada mesclada, retificação dentro da janela de 7 dias); parsing do
XML/SOAP da ANA, retry em HTTP 429 e o filtro de estações sem dado recente;
a lógica de cruzamento espacial (estação mais próxima, incluindo o
pareamento combinado INMET+ANA com desempate por recência) e temporal
(chuva acumulada 24h/72h); e as funções auxiliares do dashboard. Toda
chamada de rede é mockada, então a suíte roda sem internet.
```

- [ ] **Step 4: Verificar que a suíte e os checks de header ainda passam**

Run: `pytest -q`
Expected: 50 passed, 0 falhas.

Run:
```bash
grep -qF "Persistir o histórico de chuva incrementalmente" README.md && echo "AINDA PRESENTE (erro)" || echo "OK: removido"
grep -qF "## Roadmap" README.md && echo "OK: Roadmap presente"
grep -qF "## Limitações conhecidas" README.md && echo "OK: Limitações presente"
```
Expected: `OK: removido`, `OK: Roadmap presente`, `OK: Limitações presente`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: document incremental INMET ingestion, remove roadmap item"
```

---

## Self-Review Notes

- **Spec coverage:** todos os itens do spec (`docs/superpowers/specs/2026-08-09-ingestao-inmet-incremental-design.md`) têm task correspondente — GET condicional + CRC32 + manifesto (Task 1), merge incremental com janela de retificação (Task 2), README (Task 3).
- **Placeholder scan:** nenhum "TBD"/"TODO" — todo código e conteúdo de README está escrito por extenso.
- **Consistência de tipos/assinaturas:** `caminho_manifesto_inmet`, `baixar_zip_ano_condicional`, `_crc32_estacao`, `_carregar_manifesto`, `_salvar_manifesto` são definidos na Task 1 e consumidos com a mesma assinatura na Task 2. `ingerir_uf` mantém a assinatura pública inalterada entre a versão antiga (antes deste plano) e a nova (Task 2), preservando compatibilidade com `src/cli.py` e `src/dashboard/app.py`, que não são tocados por este plano.
- **Decisão de design registrada:** `baixar_zip_ano` (função antiga) é removida em vez de mantida como código morto ao lado de `baixar_zip_ano_condicional` — os dois testes que a cobriam foram substituídos por equivalentes da nova função (mesma cobertura de regressão, nome novo). Isso é uma escolha de implementação, não uma mudança de comportamento externo: `etag_anterior=None` reproduz exatamente o comportamento antigo (sempre baixa).
