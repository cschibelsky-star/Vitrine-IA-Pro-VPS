# Integração privada HML — Superconector V2

Camada experimental para receber solicitações autenticadas de **perfis fixos** (probe/syntax). Não é terminal, não é ferramenta pública MCP e não tem autorização para produção.

## Fatos sobre o alcance
- O executor legado de PR #76 foi testado apenas em runner CI. Reutilizá-lo aqui **não** confirma isolamento real na VPS.
- Endpoint privado `POST /v1/hml/execute` autenticado com JWT RS256, `iss`, `aud`, `tenant_id`, scope `executor:hml:run`, e SHA fixado.
- Credenciais em variáveis server-side; nenhuma chave em repositório, logs ou parâmetros do usuário.
- Docker privado isolado, sem publicação de portas, somente rede interna não roteável; execução com usuário não privilegiado, rootfs read-only, capacidades removidas, `no-new-privileges`, pids/memory limit, `tmpfs`.
- **Pendente:** provar em VPS a rede/container, o fornecimento de identidade e OIDC, validar a imutabilidade do artefato por digest, definir vínculo de autorização por missão e auditoria durável. Não habilitar por padrão.

## Critérios de aceite
1. CI instala dependências e executa negativos de autenticação, autorização, tenant, profile e SHA.
2. Em homologação isolada, comprovar `POST` autenticado e retorno de stdout, stderr e exit_code para perfil permitido.
3. Comprovar que requisições sem autorização, tenant ou SHA válidos falham antes de chamar o subprocesso.
4. Confirmar no conector MCP privado que a operação é invocável a partir do ChatGPT. Sem essa prova, não declarar execução ponta a ponta.
5. Factory, VIA, V5 e MCP público seguem imutáveis; merge e deploy exigem autorização própria.
