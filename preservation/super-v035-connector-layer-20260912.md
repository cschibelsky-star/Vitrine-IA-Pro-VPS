# Super Centro Operacional v0.3.5 - Connector Layer Recovery

Checkpoint operacional executado em 2026-09-12, sem rebuild do V5 ativo e sem SSH manual.

## Mudancas aplicadas no workspace do Super

- `super-connector/foundation_entrypoint.py`
  - runtime version: `0.3.5-existing-readonly-workspace`
  - adicionada operacao controlada `project_register_existing_readonly` para registrar diretorios existentes sob `SUPER_WORKSPACE_ROOTS` sem exigir Git, Docker ou clone.
  - o manifesto gerado usa `repository.directory = "."` e politica `read_only_workspace = true`.

- `super-connector/emergency_executor.py`
  - adicionada operacao `replace`, condicionada a `EXECUTAR`, para substituir o proprio candidate por executor independente.
  - a substituicao reaplica registry, manifests V5 legados, `/srv/projects`, `/srv/tvsumare`, audit log, Docker socket, redes e labels Traefik.

- `super-connector/docker-compose.yml`
  - `super_emergency` alterado para one-shot `replace EXECUTAR`.
  - executor temporario usa nome isolado para nao conflitar com container legado.

## Validacoes realizadas

- build do `super_connector`: OK.
- self-up direto pelo Super: corretamente bloqueado com `self_recreate_blocked`.
- build do `super_emergency`: OK.
- replace pelo executor independente: OK.
- `vitrine_super_connector_candidate`: running + healthy apos replace.
- V5 ativo nao foi rebuildado.

## Recovery workspace

O manifesto `conheca-sumare-recovery-audit` foi criado via V5 e importado pelo Super. O Super agora reconhece `/srv/projects/conheca-sumare-recovery-audit` como workspace existente, `repository_exists=true` e `repository_is_git=false`.

Leitura do recovery 3.6 via `project_read_file` foi validada em `data/attractions.json` e `data/businesses.json`, eliminando a necessidade de SSH manual para essa auditoria.
