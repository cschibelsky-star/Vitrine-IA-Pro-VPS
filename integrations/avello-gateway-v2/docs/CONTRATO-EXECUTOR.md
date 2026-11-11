# Contrato operacional — Avello Gateway V2

**Estado:** PROPOSTA OPERACIONAL REGISTRADA, NÃO HOMOLOGADA
**Data:** 2026-11-11
**Projeto:** Vitrine Avello Gateway V2
**Repositório:** cschibelsky-star/Vitrine-IA-Pro-VPS
**Branch:** feature/avello-gateway-v2-isolated-20261111
**Fonte:** PADRAO-OPERACIONAL-AGENTES-VITRINE-IA-PRO.md (proposta enviada pelo solicitante)
**Escopo autorizado:** auditar executores disponíveis e preparar contrato, sem execução de workflow externo, deploy, merge, HML ou produção.

## G0 — Inventário com evidências

| Rota | Evidência observada | Capacidade de testar MCP real | Estado |
| --- | --- | --- | --- |
| Executor local da conversa | Tentativa anterior de importar `mcp` falhou; instalação via pip falhou por DNS | Não demonstrada | BLOQUEADO neste ambiente |
| Centro Operacional V5 | `connector_health` respondeu `ok=true`, versão `0.5.14-runtime-secret-import`, registry com projetos | Não demonstrada por health | DESCONHECIDO |
| VPS Operations | `connector_health` respondeu `ok=true`, versão `2.1.0-stabilization.1`, catálogo de projetos | Não demonstrada por health | DESCONHECIDO |
| GitHub Actions | Ferramentas de leitura de runs disponíveis; não foi demonstrada execução nem instalação de dependências para esta branch | Candidato, não validado | PREVISTO |
| VPS / Docker isolado | Não foi auditado um executor exclusivo do Avello V2 | Não demonstrada | DESCONHECIDO |

Não confundir conectividade de conector, existência de código ou testes de autenticação isolados com disponibilidade de um servidor MCP funcional.

## G1 — Contrato do executor de testes

- **agent_id:** qa-avello-v2-mcp
- **versao:** 1
- **papel:** executor de QA isolado, independente da implementação
- **objetivo:** validar dependências oficiais, inicialização do servidor, descoberta de ferramentas e segurança ASGI sem afetar outros sistemas
- **entradas obrigatórias:** task_id, repo, branch, SHA exato, ambiente efêmero, dependências fixadas, testes, critérios de aceite, autorização de execução
- **saídas obrigatórias:** comando, versão Python, versão MCP, exit code, testes executados, falhas, evidências sanitizadas, SHA, handoff
- **ferramentas permitidas:** git_read, python_test_runner, package_install_em_ambiente_efemero, leitura de artefatos de teste
- **operações proibidas:** merge, deploy, migration, alterar HML ou produção, ler ou imprimir segredos, executar inferência, chamar APIs pagas, instalar no host da VPS, executar shell irrestrito
- **limites:** sem chaves reais; sem chamadas externas ao Avello; tentativas de correção limitadas a três; qualquer despesa exige aprovação específica
- **precondições:** executor comprovadamente disponível, dependências revisadas e fixadas, autorização específica para iniciar job externo
- **próximo papel:** qa-independente / VIA para verificação dos gates

## G2 — Implementação e isolamento

Os arquivos existentes permanecem na branch isolada. O workflow de testes, se aprovado, deve ser `workflow_dispatch` apenas, com permissões mínimas `contents: read`, sem secrets, sem PR/push automático e sem ações de escrita. Não criar ou disparar workflow sem autorização de escopo correspondente.

## G3 — Critérios de aceite verificáveis

1. `python -m unittest discover -s integrations/avello-gateway-v2/tests -v` executa com o pacote MCP oficial, sem stubs.
2. A versão do SDK e suas dependências são registradas e revisadas.
3. O servidor inicializa sem erros e expõe somente `gateway_status` e `gateway_models`.
4. Requisições não autorizadas falham sem alcançar o MCP; token válido alcança o MCP.
5. `gateway_models` com mock confirma GET fixo, ausência de redirects, limite de tamanho e nenhuma inferência.
6. Logs não contêm tokens ou segredos; resultados incluem SHA e status real do job.
7. Falha em qualquer gate impede homologação e gera retorno para correção.

## G4–G6 — Revisão, homologação e handoff

Revisão de segurança independente obrigatória antes de exposição pública. Testes locais ou GitHub Actions não equivalem a homologação funcional de ChatGPT/Codex. HML e produção exigem autorizações separadas. A VIA recebe o handoff com evidências e decide se os gates podem avançar; não presumir integração VIA ativa.

## Estado / próximo passo

**Estado:** BLOQUEADA para validação MCP integral; CONTRATO PREPARADO.
**Próxima decisão:** comprovar executor seguro (preferencialmente job efêmero de GitHub Actions) e autorizar separadamente criação/execução do workflow. Não usar credenciais reais nessa etapa.
