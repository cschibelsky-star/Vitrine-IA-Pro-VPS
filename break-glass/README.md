# Vitrine IA Pro Break Glass Connector

Canal de recuperação independente do MCP V5.

## Objetivo

Fornecer apenas quatro capacidades operacionais quando o MCP V5 estiver indisponível:

- `GET /health`
- `GET /v1/v5/logs?lines=N`
- `POST /v1/v5/restart`
- `POST /v1/v5/rollback`

Não existe shell remoto, acesso a banco, acesso a arquivos de projetos ou seleção arbitrária de containers.

## Arquitetura

A API HTTP roda em container não-root e **não recebe `/var/run/docker.sock`**. Ela se comunica por Unix socket com um executor local no host. O executor possui uma allowlist fixa de operações e aponta exclusivamente para o container `vitrine_mcp_v5`.

O watchdog também roda fora do MCP V5 e verifica a porta local do V5. Após falhas consecutivas ele pode reiniciar o V5 e, opcionalmente, executar rollback para uma release previamente cadastrada.

## Segurança

- token próprio em `/etc/vitrine-break-glass/api.env`;
- token diferente do MCP V5;
- comparação de token em tempo constante;
- API ligada apenas em `127.0.0.1:8871`;
- exposição externa deve ocorrer somente via Cloudflare Access ou allowlist equivalente;
- API sem Docker socket;
- API não-root UID/GID `8871`;
- Unix socket do executor `0660`, GID `8871`;
- `read_only`, `cap_drop: ALL`, `no-new-privileges`;
- rate limit e limites de logs;
- auditoria JSONL para API, executor e watchdog;
- rollback aceita somente `release_id` presente em `/etc/vitrine-break-glass/releases.json`.

## Rollback

O compose atual do V5 usa `build:` sem `image:`. Por isso o rollback não recebe imagem ou compose via requisição. Cada release autorizada registra no host:

- `image`: imagem local conhecida e preservada;
- `compose_image`: nome da imagem que o Docker Compose espera para `connector_v5`;
- `compose_file`: deve estar sob `/srv/connectors/vitrine-vps-mcp/`;
- `docker_project`: nome fixo do projeto Docker.

O executor verifica a existência da imagem, retaga a imagem conhecida para `compose_image` e recria somente o serviço `connector_v5` com `--no-build --force-recreate`.

## Watchdog

Padrões sugeridos:

- intervalo: 30 segundos;
- threshold: 3 falhas consecutivas;
- cooldown: 300 segundos;
- primeiro estágio: restart;
- segundo estágio: rollback somente se `BREAK_GLASS_AUTO_ROLLBACK_RELEASE` estiver explicitamente configurado.

Sem essa variável, o watchdog nunca escolhe uma release automaticamente.

## Arquivos

- `app.py`: API HTTP restrita;
- `executor.py`: executor local allowlisted;
- `watchdog.py`: monitor independente;
- `Dockerfile`: imagem mínima da API;
- `systemd/vitrine-break-glass-executor.service`;
- `systemd/vitrine-break-glass-watchdog.service`;
- `releases.example.json`;
- `../docker-compose.break-glass.yml`.

## Implantação

A implantação no host deve ser tratada como mudança separada. Antes de ativar:

1. preservar uma imagem V5 conhecida como boa;
2. confirmar o nome real da imagem Compose do projeto ativo;
3. criar token aleatório exclusivo do Break Glass;
4. criar `/etc/vitrine-break-glass/releases.json` a partir do exemplo, com valores reais verificados;
5. instalar executor e watchdog no host;
6. subir `docker-compose.break-glass.yml`;
7. testar `/health` localmente;
8. testar autenticação negada e aceita;
9. testar logs limitados;
10. testar restart controlado;
11. testar rollback em janela de homologação;
12. somente depois configurar Cloudflare Access/allowlist e health externo.

Não publicar a porta `8871` diretamente na Internet.
