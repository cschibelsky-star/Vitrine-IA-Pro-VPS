# Operacao supervisionada - Projeto Autonomo

## Objetivo
Coordenar tarefas de desenvolvimento com ChatGPT/Codex e Claude opcionais, preservando GitHub como fonte de verdade. O modelo de IA nao substitui as verificacoes tecnicas.

## Ciclo de trabalho
1. Identificar repositorio, branch, PR, arquivos alterados e escopo autorizado.
2. Consultar contratos, arquitetura, skills e handoff. Confirmar conectores realmente expostos.
3. Planejar mudancas pequenas; preservar arvore suja e evitar regressao.
4. Implementar em branch isolada. Se interfaces mudarem, atualizar contratos primeiro.
5. Executar verificacoes adequadas: tipos, lint, testes e seguranca, conforme a stack real.
6. Registrar evidencias, erros, custos estimados e confirmados separadamente.
7. Preparar PR e handoff. Merge, deploy e producao requerem autorizacao especifica.

## Matriz de permissoes
- ALLOW no escopo autorizado: leitura de codigo, criacao de branch, edicao isolada, testes offline, PR draft.
- ASK: merge, deploy, migrations em banco real, uso de credenciais, chamadas pagas, alteracao de permissoes e exclusoes.
- DENY: expor segredos, reset destrutivo de trabalho nao preservado, bypass de controles de acesso, declarar sucesso sem testes.

## Executor
Os PRs #57, #58 e #59 sao implementacoes candidatas distintas. Nao presumir que ai_work_delegate esteja publicado no catalogo MCP. Antes de ativar: inventariar runtime, reconciliar contrato, validar idempotencia, limites financeiros e testes offline; depois validar em HML isolada.

## Criterios de pronto
Codigo versionado; testes reais registrados; sem falhas bloqueantes conhecidas; PR revisavel; handoff atualizado. Implantacao e um marco separado.
