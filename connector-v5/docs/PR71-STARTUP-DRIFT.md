# Diagnóstico do PR #71 — bloqueio de reconstrução do V5

Data da inspeção: 2026-11-10 (Brasil). PR: https://github.com/cschibelsky-star/Vitrine-IA-Pro-VPS/pull/71

## Evidência confirmada

- Branch `fix/v5-superconector-v2-hml-allowlist` baseada em `recovery/v5-0.5.14-runtime-secret-import`: 2 commits de correção mais atualizações de CI, sem necessidade de merge.
- O PR passou a exibir `mergeable=true` após cálculo do GitHub; **mergeável não significa testado**.
- Workflow original `V5 TV Sumare policy CI` (run 42931256979) foi verde porque compilava os arquivos e verificava somente a política read-only da TV Sumaré. Ele **não executava** `test_controlled_operations_patch.py`.
- Corrigido o workflow para executar `python -m pytest -q connector-v5/test_controlled_operations_patch.py`.
- Após essa alteração, runs 42931469657 e 42931515082 falharam no passo `Execute V5 policy regression tests`.
- Stack trace do primeiro run: `RuntimeError: marketing_live_patch_version_match_count:0`.
- A fonte `connector-v5/main.py` versionada na base declara `VERSION = "0.5.11-generic-laravel-test-runner"`; `marketing_live_patch.py` exige literalmente `VERSION = "0.5.10-project-phpunit-runner-hardened"`.
- Há outra incompatibilidade estrutural: o patch espera `if operation == "tests_marketing":\n composer_lock...`, mas o main versionado usa `if operation in {"tests_marketing", "tests_laravel"}:`.
- `main_ext.py` aplica `marketing_live_patch.apply` antes de `controlled_operations_patch.apply`, portanto o patch do Superconector nem chega a executar nesse rebuild a partir da fonte.
- A implementação da exceção no PR #71 ainda não foi implantada; `controlled_service_not_allowed` é a política observada no V5 operacional.

## Decisão de segurança e próximo gate

**STOP:** Não fazer merge/deploy do PR #71 nem afirmar que o serviço `public_mcp` foi liberado.

Próximo passo seguro: reconciliar a linhagem validada do runtime V5 com Git e seus patches de inicialização, sem resetar o runtime, e executar testes de startup + regressão que comprovem a política restrita antes de nova implantação. Evitar correções cosméticas de versão que ocultem divergências de semântica.

Nenhuma alteração em TV Sumaré, produção, chaves, containers ativos, migrations ou acesso público é autorizada por este registro.

## Atualização de homologação isolada — 2026-11-10 (horário de Brasília)

- Branch `fix/v5-superconector-v2-hml-allowlist` teve `marketing_live_patch.py` reconciliado com a base `0.5.11-generic-laravel-test-runner`, preservando `tests_laravel` e gate específico do Marketing.
- Workflow `V5 TV Sumare policy CI` passou a executar regressões e smoke Docker/MCP em runner GitHub Actions, sem mounts da VPS nem credenciais reais.
- Run **42932472054**, commit `74cb52bffb77cff3f3fb59454c046e55b83604bb`: conclusão **success**. Compilação, testes de política, build Docker isolado, servidor MCP real, verificação da proteção TV Sumaré: todos aprovados.
- Log do smoke: `MCP initialize + tools/list + connector_health: PASS`, `Tool count: 33`.
- Contêiner de teste foi descartável, com filesystem somente leitura, sem privilégios e porta de loopback no runner; **não foi implantado na VPS**.
- O build do serviço `public_mcp` no V5 ativo segue bloqueado pela política atual até atualização controlada, que **não está autorizada por este PR**.
- PR #71 permanece em draft, sem merge. O teste comprova o candidato V5 isolado, não conexão do Superconector V2 ao ChatGPT.
