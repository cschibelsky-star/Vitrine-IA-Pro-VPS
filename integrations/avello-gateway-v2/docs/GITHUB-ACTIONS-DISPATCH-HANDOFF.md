# GitHub Actions dispatch — isolated adapter, NOT exposed

## Goal
Enable ChatGPT to request a narrowly scoped VIA Android source-validation run through an approved operational connector, without manual PowerShell.

## Verified connector limitation
The connected GitHub plugin can read Actions runs and write repository contents, but does not expose an initial workflow_dispatch action. GitHub Actions itself has previously built APKs; lack of a dispatch tool is not proof that GitHub runners are unavailable. Avello2 reports remote_execution=false.

## Implementation in this branch
- github_actions_dispatch.py: explicit allowlist for cschibelsky-star/JARVIS, workflow via-android-118-isolated-validation.yml and branch chore/via-android-118-structure-audit-20261113.
- Rejects arbitrary inputs, refs and workflows before accessing credentials or network.
- Requires VIA_GITHUB_ACTIONS_DISPATCH_TOKEN, intended to be provided server-side by a GitHub App with Actions:write on the single repository; never commit or print it.
- Sends fixed POST workflow_dispatch and accepts only HTTP 204 as accepted; does not claim run success or infer run_id.
- Offline tests exercise target restrictions, missing credentials, request construction and sanitized 403.
- This adapter is NOT registered in MCP, NOT deployed and NOT invoked against GitHub.

## Blocking prerequisites before exposing any tool
1. Confirm actual GitHub App Actions:write permission and approved repo installation without reading secrets.
2. Confirm workflow exists and is dispatchable on GitHub default branch under the platform's rules; do not merge into stale main merely to satisfy this.
3. Confirm workflow runs only code from allowed ref, contains no release, no signing secrets, no deploy, no installation, no artifact distribution, and has a bounded timeout.
4. Review security and test with an offline runner; record test command, exit status, SHA, and sanitized output.
5. Implement authenticated MCP ingress, caller identity and approval policy, rate limit, idempotency, audit trail, and run_id correlation before registering as a callable tool.
6. Explicitly approve HML deployment and then prove MCP tool discovery and an end-to-end permitted dispatch; production is out of scope.

## Current state
CODE PREPARED ONLY. No tests executed, no external workflow started, no plugin changed, no HML/production deployment. Preserve JARVIS build 117 and installed Samsung app.

## Verificacao offline realizada em 2026-11-14
- O codigo do adaptador e o conteudo dos quatro testes foram reproduzidos em ambiente Python isolado desta sessao (copia local para verificacao; NAO e CI do GitHub).
- Comando: python -m unittest discover -s /mnt/data/avello-dispatch-test -p 'test_*.py' -v
- Resultado: 4 testes passaram; python -m py_compile github_actions_dispatch.py passou.
- Limite: nao foram executados os testes diretamente de um checkout autenticado do repositorio nem em GitHub Actions; nao houve POST real, uso de token real ou implantacao.
- Bloqueio de ativacao: workflow_dispatch precisa ser verificado quanto a disponibilidade na branch padrao e a GitHub App precisa comprovar Actions:write. Sem esses dois gates, nao registrar ferramenta MCP nem disparar workflow.
