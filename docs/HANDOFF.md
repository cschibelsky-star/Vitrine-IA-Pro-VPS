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
