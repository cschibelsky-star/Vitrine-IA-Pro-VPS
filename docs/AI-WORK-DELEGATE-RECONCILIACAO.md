# Revisao de integracao ai_work_delegate - 2026-11-05

## Evidencias de codigo consultadas
- PR #57: connector-v5/ai_work_delegate_candidate.py e ai_delegate_v05_offline_broker.py.
- PR #58: connector-v2/mcp_runtime_hml_inventory.py.
- PR #59: connector-v2/ai_work_delegate.py, ai_work_delegate_tool.py e test_ai_work_delegate.py.
- Evidencias obtidas por patches de arquivos dos PRs; nao houve execucao dos testes.

## Divergencias bloqueantes
1. PR #57: assinatura (task_id, project, environment, scope, instruction, model, budget_brl, context_ref); somente project=via, environment=hml, model=mock, budget_brl=0, com AI_DELEGATE_MODE=mock_hml.
2. PR #59: assinatura (experiment_id, prompt, max_charge_cents, confirm); usa ledger persistente e transport Roteia, mas nao registra ferramentas automaticamente.
3. PR #58: inventario do runtime e somente leitura e nao e montado automaticamente.
4. O token de confirmacao literal EXECUTAR no PR #59 nao e comprovacao de autorizacao especifica para chamadas pagas; deve haver autorizacao externa vinculada a tarefa, modelo, limite e validade.
5. Em connector-v2/ai_work_delegate.py, a validacao `isinstance(req.max_charge_cents, int)` aceita bool em Python. Deve rejeitar explicitamente bool antes de reservar.
6. Em connector-v2/ai_work_delegate.py, a resposta do transporte e devolvida com settlement=pending_verification; nao tratar como custo efetivamente liquidado nem tarefa finalizada.
7. O limite MAX_TOTAL_CENTS=1000 e uma reserva local do PR #59; nao comprova saldo, tarifa ou custo confirmado no provedor.

## Plano minimo de reconciliacao
1. Definir contrato versionado e adaptadores sem quebrar consumidores existentes.
2. Unificar identificadores idempotentes, estados, scope, autorizacao e trilha de auditoria.
3. Preservar modo mock sem credenciais e sem chamadas externas como primeira etapa.
4. Adicionar testes para bool, reenvio com mesmo identificador, conflito de payload, concorrencia, falha ambigua, persistencia do ledger e falha fechada.
5. Inspecionar instalador, bootstrap e registro MCP real; so depois preparar HML.
6. Exigir autorizacao especifica antes de qualquer chamada paga, merge, deploy ou ativacao em runtime.

## Criterio de pronto
Ferramenta exposta no catalogo real e teste de ponta a ponta HML com mock, logs verificaveis e sem custo. Testes de integracao pagos e producao ficam fora do escopo.
