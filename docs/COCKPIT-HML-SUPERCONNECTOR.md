# Cockpit HML — operação pelo Superconector

O projeto `cockpit-escritorio-hml` registra o Cockpit Laravel da Vitrine IA Pro no Super Centro Operacional.

## Sequência autorizada

1. `project_manifest("cockpit-escritorio-hml")` para validar o manifesto.
2. `project_clone("cockpit-escritorio-hml")` para reconciliar o checkout com a branch do Escritório.
3. `project_status("cockpit-escritorio-hml")` e `project_php_lint("cockpit-escritorio-hml", "routes/cockpit.php")`.
4. `project_deploy("cockpit-escritorio-hml", environment="homologation")`.
5. `project_compose_explicit("cockpit-escritorio-hml", "docker-compose.cockpit-hml.yml", action="status")`.
6. `http_asset_probe` ou verificação equivalente em `/cockpit/login` e `/cockpit/escritorio-agentes`.

O deploy de produção permanece bloqueado pelo manifesto. O conector deve preservar árvore suja, fazer backup antes da mutação e registrar auditoria JSONL.
