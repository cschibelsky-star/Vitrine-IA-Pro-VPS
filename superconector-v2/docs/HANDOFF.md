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
