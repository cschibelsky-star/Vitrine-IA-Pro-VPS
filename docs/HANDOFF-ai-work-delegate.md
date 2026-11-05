# Handoff — ai_work_delegate / PR #57 (2026-11-05)

## Objetivo
Expor uma capacidade MCP durável para que ChatGPT possa solicitar trabalhos de programação ao Claude via Roteia sem SSH por tarefa. Reutilizar o candidato V5 existente; não criar outro conector.

## Estado comprovado
- Branch `feature/ai-work-delegate-v05-offline-hml-20261104`, PR #57 (draft), derivada de `feature/connector-via-code-pilot-mcp-20261102`.
- O overlay existente registra `ai_work_delegate` juntamente com `project_roteia_via_code_pilot_execute`.
- O Dockerfile candidato inclui o adaptador e o broker offline v0.5.
- A tool retorna `operational_broker_not_configured` por padrão.
- Somente em `AI_DELEGATE_MODE=mock_hml` e com `AI_DELEGATE_DB` configurado a tool aceita `model=mock`, `budget_brl=0` e projeto `via`, sem chamada à Roteia.
- `ai_delegate_v05_offline_broker.py`: idempotência baseada em SQLite `BEGIN IMMEDIATE`, conflito detectado e resultado explicitamente marcado `mode=mock`, `provider_invoked=false`.
- GitHub CI (branch registry + testes offline dedicados) aprovado em 2026-11-05.
- Nenhuma alteração, checkout ou deploy realizado no runtime ativo da VPS; a árvore Super existente deve ser preservada.

## Diferenças para o objetivo final
Este código **não é um executor Claude de produção**. Não existe transporte pago nem autorização real de usuário. O controle de reserva financeira por tarefa foi retirado do escopo por decisão do usuário; a integração real ainda exige registro de consumo e tratamento seguro de cobranças incertas. O mock só testa contratos internos. A tool ainda não está disponível no ChatGPT como operação real. Não converter `status=mock_completed` em sucesso Claude.

## Critérios antes de habilitar o provedor
1. Identidade do solicitante derivada de sessão/autenticação verificada pelo servidor, projeto e ambiente autorizados; rejeitar identidade fornecida como string arbitrária no prompt.
2. Backend Roteia/Claude com idempotência por tarefa, registro do custo efetivamente informado, conciliação de respostas incertas, sem retry automático depois de possível cobrança e sem recarga automática. Não implementar reserva financeira por tarefa.
3. Armazenamento SQLite/DB durável e compartilhado entre instâncias, com logs sem segredos, sem prompts sensíveis e com testes de concorrência.
4. Respostas completas ou explicitamente truncadas; não considerar HTTP 200 como trabalho útil.
5. Imagem protegida do candidato isolado, teste FastMCP real via `tools/list` e chamada mock pelo endpoint de HML; rollback documentado.
6. Conferir política de acesso da conexão MCP no ChatGPT antes de disponibilizar writes.
7. Chamada paga real somente com autorização específica posterior para a operação concreta; primeiro trabalho-alvo: auditoria VIA Android. Não exigir mecanismo de reserva financeira por tarefa.

## Restrições
Não tocar Factory principal, Super Centro ativo, produção, credenciais ou serviços pagos. Não utilizar o Vitrine API Lab como executor geral. GitHub é a fonte de verdade. Não fundir o PR nem implantar automaticamente.
