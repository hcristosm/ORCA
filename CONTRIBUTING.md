# Contribuindo com o ORCA

Obrigado pelo interesse em contribuir! O ORCA é um projeto solo de portfólio,
mas issues, PRs e sugestões são bem-vindos: geologia de risco e dados
públicos brasileiros é um espaço onde mais olhos ajudam.

Ao participar, você concorda em seguir o [Código de Conduta](CODE_OF_CONDUCT.md)
do projeto.

## Antes de abrir uma issue ou PR

- **Bugs**: descreva o comportamento esperado vs. o observado, e como
  reproduzir (comando rodado, UF/ano usados, mensagem de erro completa).
  Se envolver uma das fontes de dados (CPRM/SGB, INMET, ANA, Open-Meteo),
  vale checar antes se não é uma instabilidade pontual do endpoint: as
  quatro têm rate limit ou catálogos que mudam sem aviso (ver
  [Limitações conhecidas](README.md#limitações-conhecidas) e
  [Decisões e investigações](README.md#decisões-e-investigações) no README).
- **Ideias/funcionalidades novas**: dá uma olhada no
  [Roadmap](README.md#roadmap) primeiro. Se já está lá, comente na issue
  correspondente (ou abra uma se não existir) antes de começar a codar, pra
  alinhar escopo e evitar retrabalho.
- **Dúvidas de uso**: abra uma issue mesmo, não tem fórum/discussions
  separado.

## Ambiente de desenvolvimento

Requer Python 3.11+.

```bash
git clone https://github.com/hcristosm/ORCA
cd ORCA
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Isso instala o pacote em modo editável mais `pytest` e `responses` (mock de
HTTP). Veja a seção [Uso](README.md#uso) do README para rodar os comandos de
ingestão/exportação localmente.

## Testes

```bash
pytest
```

Toda chamada de rede nos testes é mockada (`responses`): a suíte roda sem
internet e deve continuar assim. Se você adicionar código que fala com uma
API externa, mocke a resposta em vez de bater na rede de verdade dentro do
teste.

O dashboard (`docs/dashboard/`, HTML/JS estático) não tem testes
automatizados, não há framework de teste de frontend no projeto. Se você
mexer nele, valide manualmente rodando `scripts/rodar_dashboard.sh` e
conferindo tema claro/escuro, os filtros e a camada de vento.

PRs que quebram o CI (`.github/workflows/ci.yml`, roda `pytest` a cada push
e PR) não serão mesclados até os testes passarem.

## Padrão de commits

O histórico segue [Conventional Commits](https://www.conventionalcommits.org/),
em português, no formato `tipo(escopo): descrição breve no imperativo`:

```
feat(cli): expor exportar-vento e incluí-lo em atualizar
fix(ibge): validate malha/localidades response shape
chore(dashboard): atualizar dados exportados
docs: add design spec for Open-Meteo as dashboard rain source
```

Tipos usados no projeto: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`.
O escopo é normalmente o módulo afetado (`cli`, `ibge`, `dashboard`,
`ingest`, `processing`, `export`). Mensagens de commit e PR podem ser em
português ou inglês. O README e o código-fonte são em português, mas não é
bloqueante.

## Pull requests

1. Abra a partir de uma branch própria (`feat/nome-curto`, `fix/nome-curto`),
   nunca direto em `main`.
2. Mantenha o PR focado: uma mudança lógica por PR facilita review. PRs
   grandes demais podem ser pedidos para dividir.
3. Inclua testes para código novo em `src/` (ingestão, processamento,
   exportação). Mudanças só no dashboard estático ou em documentação não
   precisam de teste automatizado.
4. Descreva o que mudou e por quê. Se corrigir um bug, inclua como
   reproduzir o problema original.
5. Espere o CI passar antes de pedir review.

Não há um linter/formatter configurado no projeto ainda, siga o estilo já
presente no arquivo que você está editando (nomes em português no domínio
de dados, docstrings quando o comportamento não é óbvio, sem comentário
redundante com o código).

## Fontes de dados sensíveis

Se sua contribuição adicionar uma nova fonte de dados (novo endpoint, nova
UF, nova API), documente no PR: a URL usada, se exige autenticação/captcha,
e qualquer rate limit observado, no mesmo nível de detalhe com que as fontes
atuais (CPRM/SGB, INMET, ANA, Open-Meteo) estão descritas no README.
