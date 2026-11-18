# Continuidade — OAuth Google

Código no PR existente, sem merge. Serviço limitado à homologação e a respostas
de modelos externos; o coordenador aplica mudanças com suas ferramentas de projeto.

## Aceite

- CI aprovado com os testes existentes e OAuth HTTP/criptografia offline.
- Checkout separado para deploy, preservando a árvore anterior.
- HTTPS retorna 401 com descoberta OAuth para solicitações sem autenticação.
- Health verifica MCP/OAuth sem inferência automática.
- Login Google real aceita somente a conta configurada, seguido de consentimento.
- ChatGPT registra cliente DCR, autentica e chama uma ferramenta com sucesso.
- GPT/Claude retornam conteúdo útil para desenvolvimento; coordenador aplica/testa.

## Operação

Credenciais Google são server-side, distintas das credenciais emitidas ao ChatGPT.
Não incluir valores nem o arquivo de credenciais no repositório ou no PR.
Rollback: restaurar checkout/Compose e flags anteriores preservados; manter volumes
e backups. Não usar reset, clean, migrações ou alterações em Core/VIA/V5.

Login real e chamada originada no ChatGPT exigem observação no cliente. Não inferir
essas etapas a partir de CI verde ou endpoint saudável.
