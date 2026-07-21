# Auditoria do Supervisor existente

Data: 2026-07-21

## Regra de arquitetura

Antes de criar qualquer componente, verificar se ele já existe. Quando existir, reutilizar, centralizar ou evoluir. Construir somente capacidades ausentes.

## Resultado

O Supervisor IA já existe no projeto `cschibelsky-star/vitrine-ai-pro`, em `services/vps-mcp-connector/supervisor.py`, consolidado com o Factory Kernel e o Operations Broker.

## Capacidades existentes

- visão consolidada da VPS;
- saúde de CPU, memória, disco e uptime;
- inventário Docker;
- estado Git;
- estado Laravel;
- filas e Redis;
- inventário Factory;
- saúde do n8n;
- planejamento operacional;
- auditoria consolidada;
- operações controladas via broker;
- confirmação obrigatória para escrita;
- log de auditoria;
- Docker Socket Proxy.

## Limitações confirmadas

O código atual é orientado a um único projeto:

- `VITRINE_APP_ROOT` define apenas um diretório principal;
- `APP_ROOT` é global;
- `LARAVEL_CONTAINER` é global;
- `REDIS_CONTAINER` é global;
- `git_status()` sempre opera no mesmo repositório;
- `laravel_status()` sempre opera no mesmo container;
- `read_laravel_log()` somente lê `storage/logs` do projeto principal;
- `factory_inventory()` é específico da Factory;
- `supervisor_overview()` não recebe `project_slug`;
- não existe catálogo central de projetos, domínios, certificados, bancos ou releases.

## Decisão

Não criar outro Supervisor.

Evoluir o Supervisor existente para um Supervisor Multi-Projetos, preservando compatibilidade com as ferramentas atuais.

## Arquitetura alvo

1. Project Registry
2. Project Resolver
3. Read-only Project Inventory
4. Git Manager por projeto
5. Runtime Manager por projeto
6. Logs Manager por projeto
7. Backup e Release Manager
8. Rollback Manager
9. Domains e Web Server Inventory
10. SSL Inventory
11. Database Inventory
12. Health Monitor consolidado

## Política de segurança

- nenhum caminho arbitrário fornecido pelo usuário;
- projetos somente por `slug` cadastrado;
- caminhos resolvidos por allowlist;
- ferramentas de escrita exigem `confirm="EXECUTAR"`;
- backup obrigatório antes de deploy;
- deploy recusado com árvore Git suja;
- comandos destrutivos de banco não expostos;
- segredos nunca retornados;
- todas as operações registradas em JSONL.

## Próxima implementação

Adicionar um registro declarativo de projetos e adaptar gradualmente as ferramentas existentes para aceitar `project_slug`, mantendo o comportamento atual como compatibilidade para o projeto `vitrine-ai-pro`.
