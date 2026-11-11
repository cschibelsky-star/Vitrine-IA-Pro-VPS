# HANDOFF — Vitrine Superconector V2 HML

Data: 2026-11-10. Estado: **codigo versionado em branch isolada; HML nao implantada**.

## Trabalho executado e evidencias

- Branch criada: `feature/superconector-v2-hml` no repositório `cschibelsky-star/Vitrine-IA-Pro-VPS`.
- Codigo V2 de servidor MCP informativo, gateway restrito, Dockerfiles/Compose e testes submetidos em `superconector-v2/`.
- ZIP fornecido: `Vitrine_Superconector_V2_HML_Preflight.zip` (fonte 0.2.0).
- Suite local do ZIP: `python -m unittest discover -s tests -q` => **20/20 OK**.
- A branch remota contem fonte derivada do ZIP, com ajustes de versao e documentacao; **a suite ainda nao foi executada contra um checkout da branch remota**, nem via CI.
- No executor local, biblioteca `mcp` nao estava instalada. Nenhum `initialize` nem `tools/list` real foi validado.
- A implementacao V2 nao esta registrada como projeto V2 ativo no V5 e nao ha Docker V2 em execucao comprovada.
- O gateway V5 permanece desligado por padrao. A rota HTTP V5 proposta `/v1/projects/{project_id}/status` nao foi confirmada no servidor V5.
- Publicacao HTTPS, OAuth MCP, integracao ChatGPT e diretório publico: **nao efetuados**.

## Gates antes da implantacao HML

1. Revisar e executar os testes a partir do commit remoto; instalar dependencias em build isolado sem acesso a producao.
2. Validar o servidor MCP de verdade por `initialize`, `tools/list` e invocacao de ferramenta informativa.
3. Auditar Docker Compose (sem socket Docker, `/root/.ssh`, `/srv/projects`, `/srv/tvsumare`).
4. Definir ambiente HML exclusivo, dominio real, DNS/HTTPS e autenticação apropriada.
5. Validar OAuth/OIDC e isolamento por tenant em ambiente autorizado; nao habilitar V5 sem contrato real e ACL.
6. Somente depois habilitar conexão MCP pelo ChatGPT e comprovar a ferramenta funcional.
7. Preparar submissao publica apenas depois de tests, identidade de publicador, politicas, review e aprovacao.

## Invariantes

Nao modificar Super legado, V4/V5 runtime, TV Sumare, producao, credenciais, migrations ou fazer merge/cutover. Nenhuma dessas operacoes esta comprovada ou autorizada por este handoff.

## Execução adicional — 2026-11-10, HML V5

- Corrigido bind do FastMCP para host 0.0.0.0 / porta 8000, stateless e resposta JSON; teste estático de escuta incluído. **Não testado em runtime real**.
- Manifest V5 `vitrine-superconector-v2-hml` criado com workspace `/srv/projects/vitrine-superconector-v2-hml`, branch `feature/superconector-v2-hml`, compose próprio e nenhum diretório compartilhado.
- Clone via V5: `ok=true`, exit_code 0; Git limpo na branch esperada.
- Docker Compose config via V5: `ok=true`, exit_code 0; porta 127.0.0.1:8878, rede `internal:true`, `cap_drop:[ALL]`, filesystem `read_only:true`, `no-new-privileges:true`.
- Tentativa controlada de BUILD serviço `public_mcp`: **NEGADA**, `controlled_service_not_allowed`. Não houve build ou start. Nenhuma tentativa de contornar allowlist foi realizada.
- Próximo bloqueio: permitir explicitamente o serviço `public_mcp` e a ação controlada de build em HML na política V5, mediante implementação/revisão específica; depois executar build, boot e teste MCP `initialize`/`tools/list` em ambiente isolado.
- Sem domínio público, OAuth operacional, acesso V5, deploy em produção, merge ou publicação.

## Homologação de protocolo MCP da V2 — 2026-11-10

- Workflow isolado `.github/workflows/superconector-v2-hml-smoke.yml` adicionado; build Docker, serviço read-only, rede local do runner e cliente MCP real.
- GitHub Actions run **42933015122**, commit `762adb59c2329ec1c312b3ef4fd135c5ee8e05ac`: **success**.
- Evidência do log: `V2 MCP initialize + tools/list + tools/call: PASS (3 tools)`.
- Executado em runner efêmero do GitHub Actions; contêiner de teste removido após execução.
- Ferramentas disponíveis: `public_capabilities`, `connection_requirements`, `service_readiness` (apenas informativas).
- V5 ativo não alterado; PR #71 ainda em draft e sem merge. Não houve implantação persistente da V2 na VPS, HTTPS público, OAuth ou conexão ao ChatGPT.
- Próximo gate: autorização controlada para instalar serviço `public_mcp` em HML isolada, com política V5 aprovada e testada; depois comprovar MCP via endpoint HML, autenticação e isolamento por cliente antes de qualquer publicação pública.

## Validação com Docker Compose real — 2026-11-10

- CI do Compose real: GitHub Actions run **42933476006**, commit `aa9fd73217c8eac1872d8a08c7d4f562ed47a7da`: **success**.
- Build, boot, MCP `initialize`, `tools/list`, `tools/call` e remoção do contêiner efêmero aprovados.
- Rede HML alterada de `internal:true` para bridge padrão, mantendo publicação exclusiva no loopback `127.0.0.1:8878:8000`; recomenda-se revisar política de egress antes de disponibilização externa.
- Execução ocorreu em GitHub Actions isolado; **não equivale à instalação persistente na VPS**.
- PR #71 permanece sem merge e V5 ativo não recebeu a nova política.
- Pendentes: habilitação controlada do serviço `public_mcp` no V5 ativo ou rota de instalação aprovada e separada, validação de host VPS, HTTPS e autenticação OAuth.
