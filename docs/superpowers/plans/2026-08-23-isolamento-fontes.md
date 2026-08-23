# Isolamento de fontes externas — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fazer o dashboard diário parar de depender de serviços `.gov.br`, movendo a ingestão CPRM/SGB para um workflow mensal com estado persistido.

**Architecture:** A ingestão CPRM sai do caminho diário e vira um workflow mensal próprio que publica GeoPackages numa branch órfã `dados-base`. O job diário passa a ler setores dessa branch e só consulta a Open-Meteo. A camada de vento é removida por inteiro, o que elimina a dependência do IBGE.

**Tech Stack:** Python 3.11, geopandas, typer, pytest, responses, GitHub Actions, gh CLI.

**Spec:** `docs/superpowers/specs/2026-08-23-pipeline-confiavel-design.md`

## Global Constraints

- Python `>=3.11`. Dependências de produção: `geopandas>=1.1.4`, `shapely>=2.1.2`, `requests>=2.34.2`, `typer>=0.27.1`. Dev: `pytest>=9.1.1`, `responses>=0.26.2`.
- Testes rodam com `pytest` a partir da raiz (`testpaths = ["tests"]`).
- Mensagens de log, docstrings e mensagens de commit em português, seguindo o padrão do repositório.
- Nenhum teste pode fazer requisição de rede real; use `responses`.
- Branch de trabalho: `fix/pipeline-confiavel`. Não commitar em `main`.
- O artefato de recuperação (`dados-orca-nacional`, run id `32611495610`) **expira em 2026-09-06**. A Tarefa 4 é bloqueante depois dessa data.

---

## Estrutura de arquivos

| Arquivo | Responsabilidade | Ação |
|---|---|---|
| `.github/workflows/atualizar-dados.yml` | Job diário: Open-Meteo + publicação | Modificar |
| `.github/workflows/ingerir-setores.yml` | Job mensal: ingestão CPRM → `dados-base` | Criar |
| `src/cli.py` | Comandos CLI | Modificar |
| `src/ingest/cprm.py` | Cliente CPRM/SGB | Modificar (timeouts) |
| `src/export/vento_data.py` | Camada de vento | **Deletar** |
| `src/ingest/ibge.py` | Cliente IBGE | **Deletar** |
| `src/processing/vento.py` | Classificação de rajada | **Deletar** |
| `src/processing/cruzamento.py` | Centroides | Modificar (remover `centroides_ibge`) |
| `src/ingest/openmeteo.py` | Cliente Open-Meteo | Modificar (remover `fetch_vento_batch`) |
| `docs/dashboard/index.html` | Front-end | Modificar (remover camada de vento) |
| `tests/test_export_vento.py`, `tests/test_ibge.py`, `tests/test_vento.py` | Testes de vento/IBGE | **Deletar** |

---

### Task 1: Estancar o sangramento

O cron diário está armado. Enquanto a SGB estiver fora, cada execução reescreve o `gh-pages` com um punhado de UFs. Esta tarefa não tem teste automatizado: é uma mudança de configuração cujo efeito é a *ausência* de execuções.

**Files:**
- Modify: `.github/workflows/atualizar-dados.yml`

**Interfaces:**
- Consumes: nada.
- Produces: nada. Tarefa 6 reverte esta mudança.

- [ ] **Step 1: Comentar o gatilho agendado**

Em `.github/workflows/atualizar-dados.yml`, comente as duas linhas do `schedule` e registre o motivo:

```yaml
on:
  # DESARMADO em 2026-08-23: enquanto a ingestão CPRM roda no caminho diário,
  # uma queda da SGB faz este workflow republicar o gh-pages com poucas UFs
  # (ocorreu nos runs #23 e #29). Rearmado na Tarefa 6 do plano
  # docs/superpowers/plans/2026-08-23-isolamento-fontes.md, depois que a
  # ingestão CPRM sair daqui.
  # schedule:
  #   - cron: "0 9 * * *"
  workflow_dispatch:
```

- [ ] **Step 2: Verificar que o YAML continua válido**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/atualizar-dados.yml')); print('YAML ok')"`
Expected: `YAML ok`

Se `yaml` não estiver instalado: `pip install pyyaml`.

- [ ] **Step 3: Confirmar que `workflow_dispatch` sobreviveu**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/atualizar-dados.yml')); print(sorted(d[True].keys()))"`
Expected: `['workflow_dispatch']` — e **não** `schedule`.

(`d[True]` não é erro de digitação: o YAML interpreta a chave `on:` como booleano verdadeiro.)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/atualizar-dados.yml
git commit -m "fix(workflow): desarmar cron diário até a ingestão CPRM sair do caminho diário

Runs #23 e #29 publicaram 1/27 e 2/27 UFs e reescreveram o gh-pages com
force_orphan. Enquanto a SGB estiver instável e a ingestão rodar no job
diário, cada execução agendada repete o estrago. Rearmado na Tarefa 6."
```

---

### Task 2: Remover a camada de vento

Deleção pura. O IBGE é usado exclusivamente pelo vento — verificado: `centroides_ibge` tem um único chamador (`vento_data.py`) e `src/ingest/ibge.py` só é importado por ele. Remover o vento elimina uma das duas dependências `.gov.br`.

**Files:**
- Delete: `src/export/vento_data.py`, `src/ingest/ibge.py`, `src/processing/vento.py`
- Delete: `tests/test_export_vento.py`, `tests/test_ibge.py`, `tests/test_vento.py`
- Delete: `docs/dashboard/data/vento_*.geojson` (9 arquivos)
- Modify: `src/cli.py` (linhas 19, 90-108, 165, 244-252)
- Modify: `src/processing/cruzamento.py` (remover `centroides_ibge`, linhas 57-66+)
- Modify: `src/ingest/openmeteo.py` (remover `fetch_vento_batch`, linha 333+, e a menção na docstring da linha 230)
- Modify: `tests/test_cruzamento.py` (remover `test_centroides_ibge_retorna_codarea_e_centroide_do_poligono`, linha 228+)
- Modify: `docs/dashboard/index.html` (remover a camada de vento)

**Interfaces:**
- Consumes: nada.
- Produces: `src.cli.app` sem os comandos `exportar-vento`; `atualizar` e `atualizar-nacional` sem chamadas a `exportar_vento`.

- [ ] **Step 1: Confirmar o estado inicial da suíte**

Run: `pip install -e ".[dev]" && pytest -q`
Expected: PASS. Anote o número de testes — ele deve cair na Etapa 6.

Se a suíte já estiver vermelha antes de qualquer mudança, **pare** e reporte: este plano assume base verde.

- [ ] **Step 2: Deletar os módulos e testes de vento/IBGE**

```bash
git rm src/export/vento_data.py src/ingest/ibge.py src/processing/vento.py
git rm tests/test_export_vento.py tests/test_ibge.py tests/test_vento.py
git rm docs/dashboard/data/vento_*.geojson
```

- [ ] **Step 3: Rodar a suíte para ver exatamente o que quebrou**

Run: `pytest -q 2>&1 | tail -30`
Expected: FAIL com `ImportError`/`ModuleNotFoundError` apontando `src.cli`, `src.processing.cruzamento` e `tests/test_cruzamento.py`.

Esta lista de erros é o mapa das próximas etapas. Não adivinhe o que remover — siga o que o interpretador apontar.

- [ ] **Step 4: Remover as referências no Python**

Em `src/cli.py`: apague o import `from src.export.vento_data import exportar_vento` (linha 19), o comando `exportar-vento` inteiro (o decorador `@app.command("exportar-vento")` e a função `exportar_vento_cmd`, linhas 90-108), a chamada em `atualizar` (linha 165 e as linhas que consomem `resultado_vento`), e o bloco de `falhas_vento` em `atualizar_nacional_cmd` (linhas 244-252, incluindo o `typer.echo` final de falhas de vento).

Em `src/processing/cruzamento.py`: apague a função `centroides_ibge` inteira e qualquer import que fique órfão.

Em `src/ingest/openmeteo.py`: apague `fetch_vento_batch` (linha 333 em diante) e ajuste a docstring da linha 230, que cita `fetch_vento_batch` como exemplo.

Em `tests/test_cruzamento.py`: apague `test_centroides_ibge_retorna_codarea_e_centroide_do_poligono` (linha 228 em diante).

- [ ] **Step 5: Rodar a suíte de novo**

Run: `pytest -q 2>&1 | tail -20`
Expected: PASS.

Se ainda houver `ImportError`, repita a Etapa 4 para o símbolo que o erro apontar.

- [ ] **Step 6: Confirmar que nenhuma referência sobrou no Python**

Run: `grep -rn "vento\|ibge\|IBGE" src/ tests/ --include=*.py`
Expected: nenhuma saída.

- [ ] **Step 7: Remover a camada de vento do front-end**

Em `docs/dashboard/index.html`, remova: os tokens `--vento-*` (linhas ~225-227), a variável `ventoGeoJSON` (~238), o bloco de `fetch` de `vento_${ufAlvo}.geojson` (~315-329), a entrada `overlays["Rajada de vento"]` e o handler do evento (~640-644), e os usos em ~759 e ~901-904.

Atenção em `malhaMunicipios` (~901): verifique se ela é usada **só** pelo vento antes de removê-la. Se tiver outro consumidor, mantenha.

Remova também as regras CSS `--vento-*` de `docs/dashboard/style.css`, se houver.

- [ ] **Step 8: Verificar o front-end**

Run: `grep -n "vento\|Vento" docs/dashboard/index.html docs/dashboard/style.css`
Expected: nenhuma saída.

- [ ] **Step 9: Conferir o dashboard no navegador**

Run: `python3 -m http.server 8000 --directory docs/dashboard`

Abra `http://localhost:8000`. O mapa deve carregar sem erro no console e sem o seletor "Rajada de vento". Os dados de AP e BA publicados hoje não estão em `docs/dashboard/data/` localmente, então o seletor de UF pode vir vazio — isso é esperado; o que importa é a **ausência de erro de JavaScript**.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: remover a camada de vento e a dependência do IBGE

O vento era o único consumidor do IBGE (centroides_ibge tinha um chamador,
src/ingest/ibge.py um importador), então removê-lo elimina uma das duas
dependências .gov.br do pipeline. No run #29 o IBGE deu timeout no runner
enquanto respondia em 0,096s a partir do Brasil.

Remove também os 9 vento_*.geojson versionados, resíduos de execuções antigas."
```

---

### Task 3: Extrair a ingestão CPRM e afrouxar seus timeouts

`atualizar-nacional` hoje faz ingestão CPRM **e** exportação. Os dois workflows precisam invocar coisas distintas, então a ingestão vira comando próprio e sai do caminho de exportação.

Com a ingestão passando a mensal, os timeouts podem ser generosos: não há pressa num job que roda uma vez por mês, e o log do run #29 provou que 30s com 7s de backoff total é curto para a SGB a partir do runner.

**Files:**
- Modify: `src/cli.py` (`atualizar_nacional_cmd`, linhas ~223-231)
- Modify: `src/ingest/cprm.py` (padrões de `fetch_setores_risco` e `ingerir_uf`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `src.ingest.cprm.ingerir_uf(uf, output, manifesto_path=None, timeout=..., max_retries=..., backoff_factor=...)`.
- Produces: comando CLI `ingerir-setores --ufs <lista> --diretorio <path>`, que sai com código 1 se **qualquer** UF falhar. `atualizar-nacional` deixa de ingerir CPRM.

- [ ] **Step 1: Escrever o teste que falha**

Adicione em `tests/test_cli.py`:

```python
@responses.activate
def test_ingerir_setores_falha_se_alguma_uf_falhar(tmp_path: Path):
    """O job mensal deve gritar quando uma UF não vem: dado congelado por um
    mês é pior que uma notificação a mais."""
    responses.add(
        responses.GET, FEATURE_LAYER_URL,
        json={"type": "FeatureCollection", "features": [_feature(1, "AP")]},
        status=200,
        match=[matchers.query_param_matcher({"where": "uf='AP'"}, strict_match=False)],
    )
    responses.add(
        responses.GET, FEATURE_LAYER_URL, status=500,
        match=[matchers.query_param_matcher({"where": "uf='BA'"}, strict_match=False)],
    )

    resultado = runner.invoke(
        app,
        ["ingerir-setores", "--ufs", "AP,BA", "--diretorio", str(tmp_path),
         "--backoff-factor", "0"],
    )

    assert resultado.exit_code == 1
    assert "BA" in resultado.output
    assert caminho_setores("AP", tmp_path).exists()
```

Acrescente `from responses import matchers` ao topo do arquivo, se ainda não estiver lá.

`--backoff-factor 0` mantém o teste rápido: sem ele, os retries dormem segundos reais.

- [ ] **Step 2: Rodar o teste para vê-lo falhar**

Run: `pytest tests/test_cli.py::test_ingerir_setores_falha_se_alguma_uf_falhar -v`
Expected: FAIL — `ingerir-setores` ainda não existe (typer sai com código 2, "No such command").

- [ ] **Step 3: Afrouxar os padrões da CPRM**

Em `src/ingest/cprm.py`, mude os padrões de `fetch_setores_risco` e `ingerir_uf`:

```python
    timeout: float = 120.0,
    max_retries: int = 5,
    backoff_factor: float = 5.0,
```

E registre o porquê logo acima de `FEATURE_LAYER_URL`:

```python
# Timeouts generosos de propósito: a ingestão roda uma vez por mês
# (.github/workflows/ingerir-setores.yml), então esperar minutos é barato,
# enquanto desistir cedo custa uma UF congelada até o mês seguinte. No run
# #29 (2026-08-23), 25 das 27 UFs morreram em `Read timed out` com
# timeout=30 e backoff de 1s/2s/4s -- sete segundos de espera total para um
# serviço brasileiro alcançado da rede do GitHub.
```

- [ ] **Step 4: Criar o comando `ingerir-setores`**

Em `src/cli.py`, acrescente:

```python
@app.command("ingerir-setores")
def ingerir_setores_cmd(
    ufs: str = typer.Option(",".join(sorted(UFS_VALIDAS)), "--ufs", help="UFs separadas por vírgula. Padrão: todas as 27."),
    diretorio: Path = typer.Option(DATA_DIR, "--diretorio", help="Diretório de dados local"),
    backoff_factor: float = typer.Option(5.0, "--backoff-factor", help="Fator de backoff entre tentativas (0 nos testes)"),
) -> None:
    """Ingere os setores de risco da CPRM/SGB para o branch `dados-base`.

    Roda mensalmente, separado da atualização diária: setor de risco é
    resultado de levantamento de campo e muda em escala de meses, então
    rebaixá-lo todo dia só expunha o dashboard à instabilidade da SGB.
    Sai com código 1 se qualquer UF falhar -- dado congelado por um mês é
    pior que uma notificação a mais.
    """
    lista_ufs = [u.strip().upper() for u in ufs.split(",") if u.strip()]
    falhas = []
    for uf in lista_ufs:
        try:
            ingerir_cprm(uf, caminho_setores(uf, diretorio), backoff_factor=backoff_factor)
        except (CPRMFetchError, ValueError) as exc:
            typer.echo(f"  FALHA na CPRM/SGB ({uf}): {exc}", err=True)
            falhas.append(uf)

    typer.echo(f"{len(lista_ufs) - len(falhas)}/{len(lista_ufs)} UF(s) ingerida(s).")
    if falhas:
        typer.echo(f"Falha na ingestão CPRM: {', '.join(falhas)}", err=True)
        raise typer.Exit(code=1)
```

- [ ] **Step 5: Rodar o teste para vê-lo passar**

Run: `pytest tests/test_cli.py::test_ingerir_setores_falha_se_alguma_uf_falhar -v`
Expected: PASS.

- [ ] **Step 6: Tirar a ingestão CPRM de `atualizar-nacional`**

Em `src/cli.py`, remova de `atualizar_nacional_cmd` o laço `for uf in lista_ufs: ingerir_cprm(...)` (linhas ~224-230), a lista `falhas_cprm` e o `typer.echo` que a reporta (~254-255). Atualize a docstring para dizer que os setores devem ter sido ingeridos antes, por `ingerir-setores`.

- [ ] **Step 7: Rodar a suíte inteira**

Run: `pytest -q`
Expected: PASS.

Testes existentes de `atualizar-nacional` que esperavam ingestão embutida vão falhar. Corrija-os para ingerir os setores antes de invocar o comando — a mudança de contrato é intencional, não um bug.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(cli): extrair ingerir-setores e afrouxar timeouts da CPRM

A ingestão CPRM sai de atualizar-nacional para que o workflow mensal e o
diário invoquem comandos distintos. O novo comando falha se qualquer UF
falhar: rodando uma vez por mês, ignorar uma perda congela a UF até o mês
seguinte.

Timeout vai de 30s para 120s e os retries de 3 para 5, com backoff de 5s.
No run #29, 25 UFs morreram em Read timed out com sete segundos de espera
total contra um serviço brasileiro alcançado da rede do GitHub."
```

---

### Task 4: Semear a branch `dados-base` com o artefato do run #28

Recuperação das 27 UFs sem depender da SGB voltar. **O artefato expira em 2026-09-06.**

Tarefa operacional, sem teste automatizado: o critério de aceite é o conteúdo da branch.

**Files:**
- Create: branch órfã `dados-base` (remota)

**Interfaces:**
- Consumes: nada.
- Produces: branch `dados-base` na raiz com `risco_<uf>.gpkg` para as 27 UFs, lida pela Tarefa 6.

- [ ] **Step 1: Confirmar que o artefato ainda existe**

Run: `gh run view 32611495610 --repo hcristosm/ORCA --json databaseId,createdAt,conclusion`
Expected: `"conclusion": "success"`, `createdAt` em 2026-08-23.

Se o artefato tiver expirado, **pare** e reporte: a recuperação passa a exigir que a SGB volte, e a Tarefa 5 vira pré-requisito desta.

- [ ] **Step 2: Baixar o artefato**

```bash
mkdir -p /tmp/orca-recuperacao && cd /tmp/orca-recuperacao
gh run download 32611495610 --repo hcristosm/ORCA --name dados-orca-nacional --dir .
ls -la
```

- [ ] **Step 3: Conferir o que veio antes de confiar**

```bash
ls *.gpkg | wc -l
ls *.gpkg | sed 's/risco_\(..\)\.gpkg/\1/' | tr 'a-z' 'A-Z' | sort | tr '\n' ' '
```

Expected: 27 arquivos, cobrindo as 27 UFs.

Se vierem menos de 27, **pare e reporte o número**. Um artefato parcial semearia a branch com o mesmo buraco que estamos consertando, e aí o dashboard ficaria permanentemente incompleto sem ninguém notar.

- [ ] **Step 4: Criar a branch órfã e publicar**

```bash
cd /tmp/orca-recuperacao
cp -r . /tmp/orca-recuperacao-backup   # rede de segurança, antes de qualquer git
git init -q && git checkout -q --orphan dados-base
git remote add origin https://github.com/hcristosm/ORCA.git
git add *.gpkg
git -c user.name=hcristosm -c user.email=hcristosm@gmail.com commit -q -m "chore(dados-base): semear setores das 27 UFs a partir do artefato do run #28

Recuperação do incidente do run #29, que republicou o gh-pages com 2 UFs e
apagou as outras 25. Como o deploy usava force_orphan, a branch tinha um
commit só e o dado não era recuperável pelo git -- esta é a cópia
sobrevivente, do artefato dados-orca-nacional do run 32611495610."
git push origin dados-base
```

- [ ] **Step 5: Verificar a branch publicada**

```bash
cd /home/lepto/Claude/ORCA
git fetch origin dados-base:refs/remotes/origin/dados-base
git ls-tree -r --name-only origin/dados-base | grep -c '\.gpkg$'
```

Expected: `27`.

- [ ] **Step 6: Confirmar que um GeoPackage abre de verdade**

```bash
git show origin/dados-base:risco_ba.gpkg > /tmp/risco_ba.gpkg
python3 -c "
import geopandas as gpd
g = gpd.read_file('/tmp/risco_ba.gpkg')
print('feições:', len(g))
print('colunas:', sorted(g.columns)[:8])
assert len(g) > 0, 'GeoPackage vazio'
assert 'num_setor' in g.columns and 'munic' in g.columns
print('OK')
"
```

Expected: contagem maior que zero e `OK`. Arquivo íntegro importa mais que arquivo presente.

- [ ] **Step 7: Registrar a ausência dos manifestos**

O artefato foi gerado com `path: data/*.gpkg` e `data/*.csv`, então **não
contém os `cprm_manifest_<uf>.json`**. Sem marcador d'água, a primeira
execução mensal vai rebaixar cada UF por inteiro em vez de incrementalmente.

Isso é aceitável e não precisa de correção: é uma ingestão completa a mais,
uma única vez, num job mensal com timeouts generosos. Anote no relatório da
tarefa para que quem executar a Tarefa 5 não interprete a demora como
defeito.

---

### Task 5: Workflow mensal de ingestão

**Files:**
- Create: `.github/workflows/ingerir-setores.yml`

**Interfaces:**
- Consumes: comando `ingerir-setores` (Tarefa 3), branch `dados-base` (Tarefa 4).
- Produces: atualizações mensais de `dados-base`.

- [ ] **Step 1: Criar o workflow**

```yaml
name: Ingerir setores da CPRM/SGB

# Setor de risco geológico é resultado de levantamento de campo e muda em
# escala de meses. Rebaixar as 27 UFs todo dia gastava 14 minutos do job
# diário e, pior, expunha o dashboard inteiro à instabilidade da SGB: nos
# runs #23 e #29 isso derrubou 22 e 25 UFs, e o dashboard foi republicado
# quase vazio. Ver docs/superpowers/specs/2026-08-23-pipeline-confiavel-design.md
on:
  schedule:
    - cron: "0 6 1 * *"
  workflow_dispatch:

concurrency:
  group: ingerir-setores
  cancel-in-progress: false

permissions:
  contents: write

jobs:
  ingerir:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v7
        with:
          python-version: "3.11"

      - name: Instalar dependências
        run: pip install -e .

      - name: Baixar setores já publicados
        # Ingestão é incremental (marcador d'água em _where_incremental):
        # partir do estado anterior evita rebaixar tudo e, se a SGB falhar
        # numa UF, o dado do mês passado continua ali. Ausência da branch
        # não é erro -- a 1a execução parte do zero.
        run: |
          mkdir -p data
          if git ls-remote --exit-code origin dados-base > /dev/null 2>&1; then
            git fetch origin dados-base:refs/remotes/origin/dados-base
            git archive origin/dados-base | tar -x -C data
            echo "Setores anteriores: $(ls data/*.gpkg 2>/dev/null | wc -l) UF(s)."
          else
            echo "Branch dados-base ainda não existe; ingestão parte do zero."
          fi

      - name: Ingerir setores
        run: python -m src.cli ingerir-setores --diretorio data

      - name: Publicar em dados-base
        # always() porque uma execução parcial ainda avançou as UFs que deram
        # certo -- vale guardar mesmo com o job marcado como falho.
        if: always()
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: data
          publish_branch: dados-base
          force_orphan: true
          user_name: "github-actions[bot]"
          user_email: "github-actions[bot]@users.noreply.github.com"
          commit_message: "chore(dados-base): atualizar setores da CPRM/SGB"
```

- [ ] **Step 2: Validar o YAML**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/ingerir-setores.yml')); print(sorted(d['jobs']['ingerir'].keys()))"`
Expected: lista incluindo `runs-on` e `steps`, sem exceção.

- [ ] **Step 3: Commit e push**

```bash
git add .github/workflows/ingerir-setores.yml
git commit -m "feat(workflow): ingestão CPRM mensal em branch própria

Isola a SGB do caminho diário. Uma queda dela passa a significar setores
com um mês de idade, não UFs sumindo do dashboard."
git push -u origin fix/pipeline-confiavel
```

- [ ] **Step 4: Disparar manualmente e observar**

```bash
gh workflow run ingerir-setores.yml --repo hcristosm/ORCA --ref fix/pipeline-confiavel
sleep 30
gh run list --workflow=ingerir-setores.yml --repo hcristosm/ORCA --limit 1
```

Acompanhe com `gh run watch <id> --repo hcristosm/ORCA`.

**Resultado esperado enquanto a SGB estiver fora:** o job **falha** no passo de ingestão, e o passo de publicação roda mesmo assim (`if: always()`), preservando os setores da Tarefa 4. Isso é o comportamento correto, não um defeito do workflow — é o alarme funcionando.

Confirme que a branch continua íntegra depois da falha:

```bash
git fetch origin dados-base:refs/remotes/origin/dados-base --force
git ls-tree -r --name-only origin/dados-base | grep -c '\.gpkg$'
```

Expected: `27`. Se cair, **pare e reporte**: significa que o passo de publicação está apagando dado bom em execução parcial, e o `force_orphan` desta branch precisa ser revisto antes de seguir.

---

### Task 6: Job diário lê `dados-base` e rearmar o cron

**Files:**
- Modify: `.github/workflows/atualizar-dados.yml`

**Interfaces:**
- Consumes: branch `dados-base` (Tarefas 4 e 5), comando `atualizar-nacional` sem ingestão CPRM (Tarefa 3).
- Produces: job diário sem nenhuma dependência `.gov.br`.

- [ ] **Step 1: Acrescentar o passo que baixa os setores**

Em `.github/workflows/atualizar-dados.yml`, logo depois de "Instalar dependências":

```yaml
      - name: Baixar setores da branch dados-base
        # Diferente do cache da Open-Meteo, que é só um empurrão inicial,
        # os setores são obrigatórios: sem eles a exportação não tem o que
        # cruzar e o dashboard sai vazio. Por isso este passo é fatal.
        run: |
          mkdir -p data
          if ! git ls-remote --exit-code origin dados-base > /dev/null 2>&1; then
            echo "::error::Branch dados-base não existe. Rode o workflow ingerir-setores.yml antes." >&2
            exit 1
          fi
          git fetch origin dados-base:refs/remotes/origin/dados-base
          git archive origin/dados-base | tar -x -C data
          TOTAL=$(ls data/*.gpkg 2>/dev/null | wc -l)
          echo "Setores carregados: $TOTAL UF(s)."
          if [ "$TOTAL" -eq 0 ]; then
            echo "::error::Nenhum GeoPackage em dados-base." >&2
            exit 1
          fi
```

- [ ] **Step 2: Rearmar o cron**

Descomente o `schedule` que a Tarefa 1 desarmou e apague o comentário de desarme:

```yaml
on:
  schedule:
    - cron: "0 9 * * *"
  workflow_dispatch:
```

- [ ] **Step 3: Validar o YAML**

Run: `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/atualizar-dados.yml')); print(sorted(d[True].keys()))"`
Expected: `['schedule', 'workflow_dispatch']`.

- [ ] **Step 4: Commit e push**

```bash
git add .github/workflows/atualizar-dados.yml
git commit -m "feat(workflow): job diário lê setores de dados-base e não toca mais na SGB

Fecha o isolamento: o caminho diário passa a depender só da Open-Meteo.
Rearma o cron desarmado na Tarefa 1."
git push
```

- [ ] **Step 5: Disparar e verificar o isolamento**

```bash
gh workflow run atualizar-dados.yml --repo hcristosm/ORCA --ref fix/pipeline-confiavel
sleep 30
gh run list --workflow=atualizar-dados.yml --repo hcristosm/ORCA --limit 1
```

Depois que terminar, com `<id>` do run:

```bash
gh run view <id> --repo hcristosm/ORCA --log > /tmp/run-novo.log
grep -c "geoportal.sgb.gov.br\|servicodados.ibge.gov.br" /tmp/run-novo.log
grep "Setores carregados\|Exportação nacional:" /tmp/run-novo.log
```

Expected: **zero** menções a `sgb.gov.br` e `ibge.gov.br` — este é o critério de aceite do plano inteiro. E `Setores carregados: 27 UF(s).`

A cobertura da exportação vai oscilar entre 70% e 100% (comportamento normal da Open-Meteo, medido em 18 runs). Não a trate como falha.

- [ ] **Step 6: Verificar o dashboard publicado**

```bash
curl -s https://hcristosm.github.io/ORCA/data/ufs_disponiveis.json | python3 -c "import json,sys; u=json.load(sys.stdin); print(len(u), 'UFs:', u)"
```

Expected: número bem maior que 2.

**Nota:** enquanto a publicação não-destrutiva do Plano 2 não existir, uma UF que falhar na Open-Meteo ainda some do site. Se este número vier abaixo de 27, é esperado e é exatamente o que o Plano 2 conserta — não retrabalhe aqui.

---

## Critério de aceite

1. `pytest -q` verde.
2. `grep -rn "vento\|ibge" src/ tests/ --include=*.py` sem saída.
3. Branch `dados-base` com 27 GeoPackages, e ao menos um abrindo com geopandas.
4. Log do job diário sem nenhuma menção a `sgb.gov.br` ou `ibge.gov.br`.
5. `ufs_disponiveis.json` publicado com bem mais que 2 UFs.

## Fora deste plano

Vão para o **Plano 2 (publicação reversível e verificada)**: mescla não-destrutiva, cache fora do `gh-pages`, abandono do `force_orphan`, selo de defasagem no front-end, alarme por defasagem, teste de fumaça e validação de sanidade.

Permanece fora de escopo, por decisão registrada na spec §7: o limiar da triagem por chuva.
