# Superconector V2 — executor experimental isolado

Estado: codigo experimental **nao ativado**; sem MCP tool, sem SSH, sem daemon, sem deploy e sem conexao com Factory/VIA. Este modulo nao faz parte do `Dockerfile`, `main.py`, `gateway.py` nem de algum container da VPS. O PR de base e `feature/superconector-v2-hml`.

## Prova de conceito verificavel
Em runner Linux descartavel do GitHub Actions, `runner.py` executa subprocessos reais com perfis FIXOS:
- `probe`: imprime `vitrine_executor_probe_ok`.
- `syntax`: analisa sintaticamente `server/main.py` e `server/gateway.py` sem executar esses arquivos.

Saida limitada inclui status, exit_code, stdout, stderr, duration_ms e SHA fornecido. O teste real usa Python `subprocess.run` sem shell, sem herdar tokens do ambiente. Chamadas fora da allowlist, sem sinal de autorizacao ou fora do contexto experimental sao rejeitadas. As validacoes do SHA sao **somente de formato**; autenticidade do commit nao foi comprovada por esse processo.

O sinal `approval=EXECUTAR` e o marcador `context=isolated-ci-only` sao barreiras locais de teste, **nao** credenciais, autenticacao ou autorizacao confiavel. Nenhum consumidor externo deve tratar esses valores como prova de identidade.

## Limites de seguranca
Esta biblioteca **nao** cria isolamento de sistema operacional: nao bloqueia rede, nao aplica cgroups/seccomp, nao configura users/namespaces e nao se conecta por SSH. Usar SOMENTE em runner descartavel de CI com repositorio de teste. Nao importar diretamente em MCP publico, V5, Factory/VIA ou servidor de producao.

Para habilitar um executor real na VPS, outro escopo e testes precisam demonstrar:
1. Identidade OIDC confiavel, tenant, autorizacao server-side por missao/operacao e trilha auditavel;
2. runner Linux realmente isolado (user nao privilegiado, rede bloqueada, filesystem minimo read-only, sem Docker socket/segredos e limites CPU/memoria/tempo);
3. repositorio/checkouts imutaveis em SHA autenticado, perfil de teste aprovado e ambiente descartavel;
4. primeira chamada **real** do MCP privado autorizado ate o executor, com job_id/exit_code/logs e reconciliacao da Factory/VIA;
5. revisao independente e homologacao especifica antes de ativar ou implantar.

**PR #71** trata exclusivamente de build/up do `public_mcp`, nao permite `run_once` nem execucao de agentes. **PR #74** e contrato de SSH separado; nao substitui os gates aqui. Sem merge, deploy, HML ou producao.
