# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.

O formato segue [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e o projeto segue [Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added
- `ruff`, `mypy` e `bandit` como gates de qualidade, rodando em CI a cada push/PR.

### Changed
- Parsing de XML da ANA migrado para `defusedxml`, eliminando a superfície de ataque de expansão de entidade.
- Tipagem reforçada em `dashboard_data`, `cprm`, `openmeteo` e `ana` (retornos, parâmetros de requisição e narrowing de `Optional`).

### Fixed
- Ajuste de `fillOpacity` na visualização de nível de risco do dashboard.

## [0.4.0] - 2026-08-24

### Added
- Cobertura nacional: ingestão e exportação para as 27 UFs (`atualizar-nacional`), com grade espacial adaptativa compartilhada entre UFs.
- Ingestão incremental da CPRM/SGB via marcador d'água (`objectid`/`data_setor`), rodando mensalmente em branch própria e isolada do pipeline diário.
- Cache SQLite incremental para a Open-Meteo, sincronizado entre execuções de CI via `gh-pages`, reduzindo o volume de requisições repetidas.
- Camada de vento por município (choropleth via malha do IBGE) e depois removida junto com a dependência do IBGE (ver "Removed").
- Triagem de municípios por chuva forte prevista, agregada à série de 30 dias no dashboard.
- Publicação não destrutiva do dashboard: guardas anti-regressão que recusam publicar um run degenerado (queda no total de UFs, piso de cobertura inválido) e alarme por defasagem em vez de cobertura simples.
- Seletor de UF no dashboard, dados guiados por `ufs_disponiveis.json`.
- `CONTRIBUTING.md` e Código de Conduta (Contributor Covenant).
- CSP no dashboard e Dependabot configurado no repositório.

### Changed
- Job diário de ingestão passa a ler os setores de risco de `dados-base` em vez de consultar a SGB diretamente, reduzindo carga na fonte externa.
- Rate limiter da Open-Meteo ajustado (espaçamento entre requisições, `max_concorrentes` reduzido) após confirmação do limite real do serviço.
- UFs que falham na primeira passada são reexportadas em série numa segunda passada.

### Fixed
- Diversas correções de robustez no pipeline nacional: orçamento de tempo honesto, pacing entre UFs, publicação parcial, normalização de resposta de lote de 1 ponto da Open-Meteo.
- Correções de estado obsoleto no dashboard ao trocar de UF (malha/nomes do IBGE, listeners, município selecionado).

### Removed
- Camada de vento e dependência do IBGE.

## [0.3.0] - 2026-08-11

### Added
- Painel de áreas customizadas: upload de GeoJSON/KML/shapefile pelo visitante, com cálculo de acumulado de chuva e trajetória prevista para a área desenhada.
- Redesenho visual do dashboard: tema cartográfico editorial (claro/escuro), tipografia própria (Source Serif 4, self-hosted), ícones Lucide.
- Screenshots do dashboard ao vivo e link do GitHub Pages no README.

### Changed
- Licença BSD 3-Clause adicionada ao projeto.

## [0.2.0] - 2026-08-10

### Added
- Ingestão da rede telemétrica da ANA como fonte de chuva complementar ao INMET, combinada por regra de distância/recência.
- Ingestão incremental do INMET por estação, com download condicional de ZIP e manifesto de CRC32 por estação.
- Cliente Open-Meteo para chuva por coordenada, adotado como fonte padrão de chuva do dashboard.
- Alertas previstos: trajetória rolante de 72h calculada a partir da previsão de chuva, exibida por setor no dashboard.
- Dashboard reescrito de Streamlit para site estático HTML/JS.

### Fixed
- Diversas correções de revisão pós-implementação nas features de ingestão ANA/INMET e alertas previstos (retry/backoff, tratamento de erro, consistência de horizonte de alerta).

## [0.1.0] - 2026-08-05

### Added
- Primeira versão do ORCA: dashboard local de risco geológico x chuva, cruzando setores de risco da CPRM/SGB com dados de chuva do INMET.

[Unreleased]: https://github.com/hcristosm/ORCA/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/hcristosm/ORCA/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/hcristosm/ORCA/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hcristosm/ORCA/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hcristosm/ORCA/releases/tag/v0.1.0
