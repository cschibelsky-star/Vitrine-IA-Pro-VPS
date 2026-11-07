# Compatibilidade Claude no Avello HML

## Mudança

- Callback remoto permitido: `https://claude.ai/api/mcp/auth_callback`, conforme a documentação oficial: https://claude.com/docs/connectors/building/authentication#callback-urls.
- Retornos ChatGPT existentes permanecem aceitos.
- A política form-action passa a incluir https://claude.ai para a navegação de retorno após o consentimento.
- DCR com cliente público (`none`), PKCE S256, verificação do recurso/escopo, Google do responsável, vínculo do callback ao cliente, CSRF e validação estrita de Origin permanecem ativos.
- Claude Code com retorno localhost está fora desta alteração. O escopo aqui é Claude hospedado, incluindo navegador e tablet.

## Validação e publicação

- Antes da alteração, a inscrição DCR com callback do Claude retornava 400 invalid_redirect_uri.
- 37 testes OAuth locais aprovados com os dois callbacks, provedores simulados, incluindo troca indevida de callback e origens/CSRF inválidos.
- A imagem HML foi publicada por overlay na imagem anterior preservada. O Dockerfile claude-hotfix verifica o hash do código original e do resultado para garantir correspondência com o código testado. Não é um build portátil; depende da imagem-base local preservada.
- O serviço está saudável após a publicação. O status do conector ChatGPT continuou respondendo, com OAuth ativo.
- A confirmação no aplicativo Claude depende da autorização do usuário. Testes simulados e prontidão do servidor não comprovam essa autorização final.
- Sem merge, mudanças em produção ou chamadas de inferência.

## Cadastro no Claude

1. Abrir Claude no navegador do tablet e acessar Personalizar > Conectores > Adicionar conector personalizado.
2. URL do servidor: `https://avello.hml.vitrineiapro.com.br/mcp`, sem barra final ou parâmetros.
3. Usar OAuth, Entrar agora e Registrar automaticamente (DCR). Não informar Client ID/Secret do Google e não selecionar identidade publicada/CIMD para este servidor.
4. Fazer o login Google com a conta já autorizada, confirmar o consentimento e habilitar o conector na conversa.
5. Solicitar apenas `avello_status` para a primeira verificação, sem inferência.
