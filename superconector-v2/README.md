# Vitrine Superconector V2 — HML

Estado: **preparação**, não implantado.

## Objetivo
Servidor MCP independente do workspace ChatGPT anterior, com caminho de publicação pública após testes e revisão.

## Referência de origem
Pacote validado nesta conversa: `Vitrine_Superconector_V2_HML_Preflight.zip`, derivado da versão 0.2.0.

**Atenção:** o pacote-fonte ainda precisa ser sincronizado integralmente com esta branch antes de qualquer build/deploy. Este registro não implica que o código do ZIP já esteja no GitHub.

## Estado de validação
- 20 testes unitários locais aprovados com bibliotecas disponíveis no ambiente de inspeção.
- SDK Python `mcp` indisponível no executor local: handshake `initialize` e `tools/list` ainda não comprovados.
- Gateway V5 desabilitado por padrão; contrato real de API/credenciais do V5 não confirmado.
- Nenhuma publicação HTTPS, deploy ou integração ChatGPT realizada.

## Gates obrigatórios
1. Versionar todo o código e manter os manifests/lockfiles necessários.
2. Remover qualquer privilégio de Docker socket, acesso a `/root/.ssh`, `/srv/projects`, `/srv/tvsumare` e hosts de produção.
3. Preparar HML com namespace e domínio exclusivos, segregação de rede e variáveis seguras.
4. Validar dependências, boot, MCP `initialize` e `tools/list` em execução real.
5. Testar OAuth/OIDC e autorização por tenant, inclusive casos de negação.
6. Validar leitura efetiva no V5 apenas após contrato server-side e permissão aprovados.
7. Conectar cliente MCP/ChatGPT e demonstrar descoberta e execução de ferramenta.
8. Submissão pública somente com documentação e aprovação próprias.

Sem merge, deploy produtivo, migration ou cutover por esta branch.
