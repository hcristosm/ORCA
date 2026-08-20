# Limpeza do repositório e deploy mais leve — Plano de execução

> **Para quem for executar:** este é um plano operacional (git + infra de CI/deploy), não uma feature de código com TDD. Execução inline nesta sessão, com checkpoint de confirmação do usuário antes de qualquer push destrutivo (force-push).

**Objetivo:** Parar de inchar o histórico do git com os dados diários do dashboard (136MB, recommitados toda vez), reduzir o `.git` já acumulado, e tornar o deploy do GitHub Pages mais leve e confiável (hoje falha total ou parcialmente).

**Diagnóstico (confirmado):**
- `docs/dashboard/data/` tem 136MB de JSON/GeoJSON gerados por [scripts/atualizar_dados.py](../../../scripts/atualizar_dados.py).
- O workflow [.github/workflows/atualizar-dados.yml](../../../.github/workflows/atualizar-dados.yml) roda todo dia (cron `0 9 * * *`), regenera esses arquivos e faz `git commit` + `git push` na `main`. Cada execução duplica os blobs grandes no histórico (ex.: `series_sc.json` de 13MB aparece 5x no histórico).
- `.git` já está em 45MB e cresce sem limite a cada dia que os dados mudam.
- O GitHub Pages publica esse mesmo diretório (`docs/dashboard`) direto da `main` — ou seja, cada push de dados é também um deploy, competindo com o próprio job de atualização (que já tem lógica de retry por causa de `push` não-fast-forward).

**Solução:**
1. Parar de versionar `docs/dashboard/data` na `main`. Os arquivos de dados passam a ser gerados e publicados sem nunca entrar no histórico da `main`.
2. Publicar o dashboard (estáticos da main + dados frescos gerados no job) numa branch `gh-pages` dedicada, resetada (orphan) a cada deploy — nunca acumula histórico.
3. Apontar o GitHub Pages para essa branch `gh-pages`.
4. Reescrever o histórico da `main` (git filter-repo) para remover as versões antigas de `docs/dashboard/data` já commitadas, encolhendo o `.git` de forma permanente.

**Stack:** GitHub Actions, git, `git filter-repo`, `peaceiris/actions-gh-pages`.

---

## Tarefa 1 — Parar de versionar dados do dashboard na main

**Arquivos:**
- Modificar: [.gitignore](../../../.gitignore)
- Remover do índice (mantendo em disco): `docs/dashboard/data/`

- [ ] Adicionar `docs/dashboard/data/` ao `.gitignore`.
- [ ] `git rm -r --cached docs/dashboard/data` (remove do controle de versão, mantém os arquivos localmente).
- [ ] Commit: `chore: parar de versionar dados gerados do dashboard`.
- [ ] Verificar: `git status` não deve mais listar `docs/dashboard/data` como tracked; `ls docs/dashboard/data` ainda mostra os arquivos no disco.

## Tarefa 2 — Trocar o passo de commit por deploy em branch gh-pages orphan

**Arquivos:**
- Modificar: [.github/workflows/atualizar-dados.yml](../../../.github/workflows/atualizar-dados.yml)

- [ ] Remover o step "Comitar dados exportados do dashboard estático" (o bloco que faz `git add docs/dashboard/data`, `git commit`, `git pull --rebase` + `git push` com retry).
- [ ] Adicionar um step novo, após a geração dos dados, usando `peaceiris/actions-gh-pages@v4`:

```yaml
      - name: Publicar dashboard no GitHub Pages
        if: always()
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs/dashboard
          publish_branch: gh-pages
          force_orphan: true
          user_name: "github-actions[bot]"
          user_email: "github-actions[bot]@users.noreply.github.com"
          commit_message: "chore(dashboard): publicar dados atualizados"
```

  `force_orphan: true` é o que garante que a branch `gh-pages` é resetada a cada deploy (um único commit, sem acumular histórico) — resolve o problema de crescimento para sempre.
- [ ] Commit: `ci: publicar dashboard via branch gh-pages orphan em vez de commit na main`.
- [ ] Verificar (sintaxe): `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/atualizar-dados.yml'))"` sem erro.

## Tarefa 3 — Apontar o GitHub Pages para a branch gh-pages

Isso é uma mudança de configuração do repositório no GitHub (Settings → Pages), fora do alcance de `git`. Requer ação do usuário (ou `gh`/API com permissão de admin do repo, que não está disponível nesta sessão — `gh` CLI não está instalado).

- [ ] Usuário: ir em `Settings → Pages` do repositório e mudar "Build and deployment → Source" para "Deploy from a branch", branch `gh-pages`, pasta `/ (root)`.
- [ ] Rodar o workflow manualmente uma vez (`workflow_dispatch`) para a branch `gh-pages` ser criada com conteúdo.
- [ ] Verificar: após o workflow rodar, `git ls-remote origin gh-pages` mostra a branch existindo; o site publicado carrega o dashboard normalmente.

## Tarefa 4 — Reescrever o histórico da main para encolher o .git

**Ferramenta:** `git filter-repo` (precisa ser instalado: `pip install --user git-filter-repo`).

- [ ] Confirmar que não há mudanças não commitadas: `git status` limpo.
- [ ] Rodar: `git filter-repo --path docs/dashboard/data --invert-paths --force`
  (remove todas as versões históricas de `docs/dashboard/data` de todos os commits da main; o `filter-repo` reescreve todos os hashes de commit).
- [ ] Verificar localmente: `du -sh .git` deve cair bem abaixo dos 45MB atuais.
- [ ] **Checkpoint de confirmação com o usuário antes do próximo passo** — reescrever histórico exige force-push e invalida clones locais existentes de colaboradores.
- [ ] Force-push: `git push origin main --force` (e `git push origin --force --tags` se houver tags).
- [ ] Verificar: clonar o repo em uma pasta temporária e conferir `du -sh .git` no clone fresco; confirmar que `docs/dashboard/data` não aparece mais em `git log --all -- docs/dashboard/data`.

---

## Riscos e observações

- Colaboradores com clone local da `main` (não só bots) precisarão re-clonar ou fazer `git fetch && git reset --hard origin/main` depois do force-push — comunicar antes.
- Branches do dependabot (`dependabot/pip/...`) apontam para commits antigos da main; após o rewrite elas podem ficar com base divergente. O GitHub geralmente lida bem (dependabot recria o PR), mas vale checar depois.
- `force_orphan: true` faz a branch `gh-pages` nunca ter histórico útil — isso é intencional (é só o artefato de deploy, não precisa de histórico).
