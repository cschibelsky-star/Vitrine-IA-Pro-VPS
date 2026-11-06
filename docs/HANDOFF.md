# Handoff — ativação do Vitrine Avello MCP (2026-11-05)

## Objetivo
Entregar um servidor MCP privado por HTTPS que permita a ChatGPT e Claude chamar GPT/Claude via Avello. Primeiro caso de teste futuro: régua de notícias TV Sumaré, somente em PR de homologação.

## Estado confirmado
- PR #60 (branch `feature/avello-private-mcp-hml`): servidor FastMCP, adaptadores GPT/Claude, Compose isolado e testes offline. Workflow Avello offline #42021216618 aprovado. Não implantado nem validado com API real.
- PR #61 (branch `feature/avello-v5-service-policy-hml`): entrada restrita em `connector-v5/controlled_operations_patch.py` para projeto `vitrine-avello-private`, compose `integrations/avello-private-mcp/compose.hml.yml`, serviço `avello_private_mcp`, operações build/up/status/logs. CI de política e CI TV Sumaré aprovados no commit `52a06e8dfa3b7726bf774d0d60b47389648bdfa9`. Não mergeado nem implantado.
- Registro do projeto existe no Super e V5; checkout `/srv/projects/vitrine-avello-private/repository`; variável `AVELLO_CALLS_ENABLED=false` presente. Ausentes: `MCP_BEARER_TOKEN`, chaves GPT/Claude e ID de modelo Claude.
- Runtime V5 `0.5.14-runtime-secret-import` ainda retorna `controlled_service_not_allowed` para `avello_private_mcp`; nenhum container Avello iniciado.
- Checkout `v5-reviewed-homologation-hml` está sujo em `connector-v5/main.py` e `docker-compose.v5-recovery-candidate.yml`; não sobrescrever nem resetar.

## Plano técnico seguro
1. Validar a rota de deploy/rollback de candidato V5 sem modificar o checkout sujo.
2. Preservar alterações existentes antes de qualquer operação potencialmente conflitante.
3. Aplicar somente a política revisada após autorização e validação do runtime-alvo.
4. Confirmar que o erro `controlled_service_not_allowed` desapareceu em V5 por `project_compose_service_status`.
5. Injetar credenciais por importação server-side segura, sem expor conteúdo em chat, Git ou logs. Não usar chave já exibida na conversa para execução automática.
6. Verificar autenticação real compatível com clientes ChatGPT e Claude, HTTPS, `tools/list` e `avello_status` antes de habilitar chamadas.
7. Validar chamadas reais de GPT/Claude separadamente e registrar erro/uso sem segredos.
8. Somente depois iniciar piloto TV Sumaré em PR independente.

## Proibições e observações
Não assumir que CI aprovado significa deploy; não usar deploy genérico de Laravel/produção; não fazer merge, migrações, reiniciar V5 vivo ou editar Core/VIA/TV Sumaré sem autorização específica. O plugin privado do ChatGPT hoje é uma Skill, e não um endpoint MCP remoto ativo.

## Atualização — preflight completo de inicialização do V5 (2026-11-05, noite)
- Workflow `Avello V5 runtime preflight` #42141525212 construiu imagem Docker isolada com sucesso, mas falhou no import de `main_ext.py`: `marketing_live_patch_version_match_count:0`. Isto revela incompatibilidade do `connector-v5/main.py` canônico (VERSION `0.5.11-generic-laravel-test-runner`) com `marketing_live_patch.py` (exige `0.5.10-project-phpunit-runner-hardened`).
- Foi testada compatibilidade estrita para as duas strings da versão no commit `84646a1`, mas o preflight #42141638431 continuou falhando com `marketing_live_patch_commands_match_count:0`: a divergência envolve a implementação, não apenas a string da versão.
- A tentativa de alteração da versão foi **revertida** no commit `fc2c5e5` para manter fail-closed e não mascarar incompatibilidade estrutural.
- CI de política Avello e CI TV Sumaré passaram para o commit `84646a1`, mas o preflight integral de boot está **vermelho**. Portanto, PR #61 **não apto a deploy**.
- O checkout `v5-reviewed-homologation-hml` permanece com alterações locais não commitadas; não fazer reset ou checkout forçado.
- Próxima correção de engenharia: identificar a revisão canônica completa de `main.py` compatível com ambos os patches já usados no V5 ativo (sem ler secrets); reconstruir e testar imagem inteira em CI isolado antes de atualizar qualquer runtime. Evitar editar `marketing_live_patch.py` para ignorar validações de código.
- Não houve deploy, reinício de V5, merge, provisionamento de credenciais nem chamada Avello paga.
