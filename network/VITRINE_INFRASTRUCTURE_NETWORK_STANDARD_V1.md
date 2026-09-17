# Vitrine Infrastructure Network Standard V1

## Objetivo
Eliminar colisoes de enderecos Docker e impedir que a indisponibilidade temporaria de um servico permita que outro container ocupe seu endereco.

## Regra principal
Na rede compartilhada de borda `n8n-traefik_app_network`, novos projetos e servicos NAO devem declarar `ipv4_address` fixo.

A comunicacao entre containers deve usar DNS Docker pelo nome/alias do servico. Exemplos: `redis`, `postgres`, `n8n-main`.

## Incidente de referencia - 2026-09-17
O stack n8n/Traefik utilizava IPs fixos 172.24.0.10 a 172.24.0.14. Durante indisponibilidade, outros containers receberam enderecos dessa faixa, impedindo Traefik e Redis de retornar com `Address already in use`.

A correcao operacional removeu os `ipv4_address` fixos de Traefik, Redis, PostgreSQL, n8n-main e n8n-worker. Docker IPAM passou a alocar os enderecos e a comunicacao permanece por DNS Docker.

## Politica
1. Proibido adicionar `ipv4_address` em `n8n-traefik_app_network` sem excecao arquitetural documentada.
2. Redis e PostgreSQL nao devem depender de endereco IP numerico para descoberta.
3. Aplicacoes publicadas pelo Traefik devem referenciar a rede pelo nome, sem reservar IP.
4. Provisionamento deve executar Network Guard antes de compose/deploy.
5. Network Guard deve bloquear compose que introduza `ipv4_address` na rede compartilhada.
6. Alteracoes de rede devem preservar configuracao anterior e possuir rollback.
7. GitHub e a fonte de verdade do padrao e das validacoes.

## Network Guard - requisitos
O preflight deve verificar pelo menos:
- `ipv4_address` proibido na rede compartilhada;
- hostname/rota Traefik duplicada;
- porta publicada duplicada;
- network externa inexistente;
- alias conflitante quando relevante;
- compose valido antes de qualquer recriacao.

Falha de qualquer regra critica deve retornar `DEPLOY_BLOCKED` antes de alterar runtime.

## Evolucao recomendada
Separar progressivamente a rede de borda da rede interna do n8n:
- edge: Traefik e frontends publicados;
- internal: n8n-main, n8n-worker, Redis e PostgreSQL.

Essa separacao deve ocorrer em cutover controlado posterior, sem apagar volumes ou bancos e com validacao de rollback.
