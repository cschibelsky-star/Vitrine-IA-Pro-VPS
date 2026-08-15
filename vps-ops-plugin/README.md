# Vitrine VPS Ops

Plugin interno `tool-only` para administração controlada da infraestrutura Vitrine IA Pro a partir do ChatGPT.

## Objetivo

Separar a administração da VPS do MCP operacional dos produtos. O plugin não oferece shell genérico e não aceita nomes arbitrários de containers ou serviços para ações privilegiadas.

## Arquitetura

ChatGPT -> Vitrine VPS Ops -> Ops API / Ops Broker -> VPS

O MCP operacional dos produtos permanece separado.

## Ferramentas v0.1

### Leitura

- `server_health`
- `project_status`
- `project_read_file`
- `project_shared_read`
- `mcp_status`
- `mcp_health`

### Mutação controlada

- `mcp_restart(confirm="EXECUTAR")`

## Regras de segurança

- sem `exec`, `shell`, `ssh_exec` ou comando arbitrário;
- IDs de projeto e caminhos são validados pelo Ops API;
- leitura de dados compartilhados respeita `shared_directories` do manifesto;
- `secrets`, symlinks, travessia `..` e arquivos não permitidos permanecem bloqueados;
- restart do MCP atua somente no runtime fixo allowlisted;
- ferramentas mutáveis exigem confirmação explícita quando aplicável;
- o token do Ops Broker fica somente em variável de ambiente.

## Runtime HML

Container: `vitrine_vps_ops_plugin_hml`

Porta local: `127.0.0.1:18181 -> 8181`

Health: `/health`

MCP: `/mcp`

## Variáveis

- `OPS_API_URL`
- `OPS_BROKER_URL`
- `OPS_BROKER_TOKEN`
- `OPS_REQUEST_TIMEOUT_MS`
- `HOST`
- `PORT`

## Próximas capacidades planejadas

Adicionar somente após endpoints allowlisted no backend:

- `project_build_hml`
- `project_restart_hml`
- `project_healthcheck`
- `container_logs` com alvo allowlisted
- `backup_create`
- `rollback_last_release`
- `mcp_update`
- `mcp_rollback`

Não adicionar terminal genérico.
