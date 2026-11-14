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

## Atualizacao 2026-11-14 — registro MCP bloqueado
- server.py recebeu registro condicional da ferramenta via_android_request_validation, desligada por padrao (VIA_GITHUB_DISPATCH_TOOL_ENABLED nao habilitado).
- A funcao ainda depende de um gate server-side VIA_GITHUB_DISPATCH_APPROVED; uma flag global NAO substitui autorizacao por usuario, nem permite implantacao. Nao ativar ambas as flags antes de substituir a flag por verificacao autenticada por chamada e auditoria persistente.
- Verificacao de GitHub: branch padrao de JARVIS e main, contendo apenas android-apk-hml.yml e android-apk.yml; workflow via-android-118-isolated-validation.yml existe somente na branch experimental. O workflow_dispatch nao esta pronto para acionamento manual por esta rota.
- Nenhuma chamada de dispatch, deploy, alteracao de credencial ou exposicao MCP foi realizada.

## Atualizacao — politica de autorizacao isolada
- Criados dispatch_authorization.py e tests/test_dispatch_authorization.py no PR #75.
- Politica: identidade de origem autenticada (exigida a montante), assinatura HMAC por requisicao vinculada ao destino fixo, janela de 120 segundos e nonce de uso unico gravado em SQLite.
- Esta politica nao esta integrada ao ingress MCP; nao existe endpoint de dispatch exposto. A auditoria atual e apenas ledger de nonce, nao um historico completo de requisicoes e resultados.
- Testes adicionados, mas ainda nao comprovados por execucao de CI; verificar e corrigir falhas antes de habilitar.
- Necessario validar autenticacao real do solicitante, auditoria persistente de decisoes e resultados, rate limiting, correlacao do run_id, permissao Actions:write e disponibilidade do workflow na branch padrao.

## Integracao autenticada por chamada — 2026-11-14
- auth_guard.py recebe headers de aprovacao como dados nao confiaveis e os propaga em ContextVar, isolados por requisicao ASGI. Bearer continua obrigatorio.
- dispatch_request_context.py define o contrato; server.py registra via_android_request_validation SOMENTE com VIA_GITHUB_DISPATCH_TOOL_ENABLED=true (desligado por padrao). A ferramenta exige assinatura HMAC valida e nonce atomico antes de chamar o adaptador.
- Adicionados testes offline test_dispatch_ingress.py para bloqueio 401, ausencia/duplicacao de headers e isolamento de contexto.
- ALERTA: nenhuma identidade de emissor confiavel foi integrada; assinatura HMAC nao deve ser emitida pelo proprio usuario ou ChatGPT. Falta autorizacao por operador confiavel, rate limit, auditoria de dispatch e correlacao run_id. Nao habilitar o flag nem implantar.
- Testes adicionados nesta etapa ainda exigem execucao em checkout real ou CI; o PR continua draft e nao foi acionado workflow externo.
