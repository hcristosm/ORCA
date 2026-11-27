# Contribuindo com o ORCA

Obrigado pelo interesse em contribuir! O ORCA é um projeto solo de portfólio,
mas issues, PRs e sugestões são bem-vindos: geologia de risco e dados
públicos brasileiros é um espaço onde mais olhos ajudam.

Ao participar, você concorda em seguir o [Código de Conduta](CODE_OF_CONDUCT.md)
do projeto.

## Antes de abrir uma issue ou PR

- **Bugs**: descreva o comportamento esperado e o observado, e como
  reproduzir (comando rodado, UF, critério usado, mensagem de erro completa).
  Se envolver uma fonte de dados (BELUGA, Open-Meteo), confira antes se não é
  uma instabilidade pontual (ver
  [Limitações conhecidas](README.md#limitações-conhecidas)). Setor errado ou
  faltando é assunto do [BELUGA](https://github.com/hcristosm/BELUGA), que é
  quem coleta e valida os setores; o ORCA só consome a publicação v1.
- **Ideias e funcionalidades novas**: comente na issue correspondente (ou abra
  uma) antes de começar a codar, para alinhar o escopo.
- **Dúvidas de uso**: abra uma issue. Não há fórum separado.

## A prioridade é confiabilidade

O pipeline depende de fontes que caem, mudam de formato e devolvem resposta
vazia com HTTP 200. **Funcionar sem quebrar vale mais que qualquer
funcionalidade nova.** Ao mexer em ingestão, assuma que a fonte vai falhar e
trate o caso: arquivo truncado, sha256 que não bate, publicação que encolheu,
erro com status 200. Todo caso de falha tem teste com a rede mockada.

Duas regras valem para todo o código:

- **Caminhos moram em `src/config.py`.** Nunca monte um caminho de `data/` à
  mão; use `caminho_setores_beluga()`, `caminho_manifesto_beluga()` e os
  demais. O prefixo `beluga_` do GeoPackage é load-bearing: o escopo da mescla
  é medido por ele, e escopo vazio desliga o piso de cobertura.
- **Publicar menos do que já está no ar é proibido.** O deploy apaga do
  `gh-pages` o que não está em `docs/dashboard/`: publicar com `data/` vazio
  apaga as 27 UFs. A guarda em
  `scripts/conferir_publicacao.py` recusa esse caso, sempre grava
  `publicar=false` antes de sair com 1 (o output pula a publicação; o exit 1
  deixa a recusa visível) e é coberta por `tests/test_conferir_publicacao.py`.
  Não mude essas propriedades sem olhar esses testes primeiro.

E uma regra para quem opera os workflows: **nunca julgue um run pelo status.**
Dois runs já apagaram o dashboard fechando como `success`. Confira nos logs a
contagem de UFs e o teste de fumaça.

## Ambiente de desenvolvimento

Requer Python 3.11+.

```bash
git clone https://github.com/hcristosm/ORCA
cd ORCA
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Veja a seção [Uso](README.md#uso) do README para rodar a ingestão e a
exportação localmente, e `scripts/rodar_dashboard.sh` para abrir o dashboard.

## Testes e gates

O CI roda estes quatro comandos a cada push e PR. Rode-os antes de commitar:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
.venv/bin/python -m bandit -q -c pyproject.toml -r src
```

Toda chamada de rede nos testes é mockada (`responses`): a suíte roda sem
internet e deve continuar assim. Código novo que fala com uma API externa
precisa de teste com a resposta mockada, incluindo os casos de falha.

Os cálculos do dashboard que não dependem de DOM ficam em
`docs/dashboard/calculo.js` e têm testes em `tests/js/calculo.html`, numa
página, porque o projeto não usa Node. Eles rodam junto com o `pytest`
(`tests/test_js.py` abre a página no Chrome do sistema), então não há nada a
lembrar de rodar à parte. Para olhar a página, sirva a raiz do repositório com
`python3 -m http.server 8001` e abra
`http://localhost:8001/tests/js/calculo.html`.

Lógica nova do front-end que dá para separar do DOM vai para o `calculo.js`,
com teste.

O resto do dashboard é validado à mão: confira o desktop e o celular (abaixo de
768px), os temas claro e escuro, e o console sem erro.

## Padrão de commits

O histórico segue [Conventional Commits](https://www.conventionalcommits.org/),
em português, no formato `tipo(escopo): descrição breve`:

```
feat(dashboard): busca acha município sem setor da CPRM
fix(ingest): protege a poda, o marcador e a paginação da CPRM
docs(readme): reorganiza os READMEs
chore(deps-dev): atualiza ruff
```

Tipos usados: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`. O escopo é
normalmente a área afetada (`ingest`, `processing`, `export`, `dashboard`,
`ci`, `readme`).

Código, comentários, commits e documentação são em português. Toda mudança
relevante ganha uma entrada no `CHANGELOG.md`, em `[Unreleased]`, agrupada por
`FEATURES`, `FIXES`, `REFACTOR` ou `CHORE`.

## Pull requests

1. Abra a partir de uma branch própria (`feat/nome-curto`, `fix/nome-curto`).
2. Mantenha o PR focado: uma mudança lógica por PR.
3. Inclua testes para código novo em `src/` e para lógica nova do
   `calculo.js`.
4. Descreva o que mudou e por quê. Se corrigir um bug, inclua como reproduzir
   o problema original.
5. Espere o CI passar antes de pedir review.

Siga o estilo do arquivo que você está editando: nomes em português no domínio
dos dados, e comentário que explica o porquê, não o que o código já diz.

## Releases

Bump da versão no `pyproject.toml`, entrada no `CHANGELOG.md` e tag `vX.Y.Z`.
A tag dispara o `release.yml`: confira que os artefatos existem, não só que o
run passou.

## Fontes de dados novas

Se sua contribuição adicionar uma fonte de dados, documente no PR a URL usada,
se exige autenticação, o limite de requisições observado e como a fonte falha
(fora do ar, resposta vazia, mudança de formato). O código precisa tratar cada
um desses casos sem apagar dado que já está publicado.
