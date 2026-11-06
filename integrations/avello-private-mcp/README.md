# Vitrine Avello Private MCP — homologação

Ponte privada para consultas GPT/Claude. Gera respostas e sugestões de código; o
ChatGPT coordenador revisa, aplica alterações e executa testes com suas próprias
ferramentas de projeto. Este serviço não executa código, shell, deploy ou Git.

## Login Google e ChatGPT

O servidor usa OAuth com PKCE S256 do SDK MCP. O login Google usa OpenID Connect
via Authlib, verificando assinatura, issuer, audience, nonce, expiração, e-mail
verificado e a conta explicitamente permitida. Solicita apenas `openid email`.

Após o login, há uma confirmação local para o cliente registrado. O conector emite
credenciais MCP próprias vinculadas ao recurso
`https://avello.hml.vitrineiapro.com.br/mcp` e ao escopo `avello:use`.
Tokens e códigos são indexados por hash; registros SQLite são criptografados.
Códigos duram dois minutos e são consumidos uma vez. Access tokens duram uma hora;
refresh tokens duram sete dias e são rotacionados, invalidando o par anterior.
A revogação invalida os dois tokens da família.

No cliente, cadastrar a URL MCP com **OAuth**, **Dynamic Client Registration (DCR)**
e método público `none` (PKCE). As credenciais Google NÃO são client ID/secret do
ChatGPT: pertencem exclusivamente ao trecho servidor → Google.
Callbacks DCR são restritos aos caminhos OAuth oficiais do ChatGPT; o SDK vincula
cada URI exata ao cliente registrado. CIMD não é anunciado.

## Configuração

Usar armazenamento de segredos aprovado; nunca versionar valores reais.

| Variável | Finalidade |
| --- | --- |
| `AVELLO_GOOGLE_CLIENT_ID` | Aplicativo Web OAuth Google |
| `AVELLO_GOOGLE_CLIENT_SECRET` | Segredo desse aplicativo |
| `AVELLO_OAUTH_SESSION_SECRET` | Segredo aleatório persistente, mínimo 32 caracteres |
| `AVELLO_OAUTH_ALLOWED_EMAIL` | Única conta Google autorizada |
| `AVELLO_OAUTH_ENABLED` | Login Google, padrão false |
| `MCP_BEARER_TOKEN` | Credencial privada de diagnóstico, mínimo 32 caracteres |
| `AVELLO_GPT_API_KEY` | Credencial Avello GPT separada |
| `AVELLO_CLAUDE_API_KEY` | Credencial Avello Claude separada |
| `AVELLO_CLAUDE_MODEL` | Modelo Claude configurado |
| `AVELLO_CALLS_ENABLED` | Consultas gerais, padrão false |

Callback Google: `https://avello.hml.vitrineiapro.com.br/oauth/google/callback`.
Manter um worker, HTTPS, volume /data persistente e protegido e logs de acesso
desligados para não registrar códigos OAuth. Não trocar o segredo de sessão sem
planejar a invalidação dos registros criptografados.
OAuth habilitado com configuração incompleta falha fechado no início.
Quando desabilitado, mantém o Bearer anterior.

## Modelos e limites

GPT padrão: gpt-6.1-sol; Astra excluído. Claude usa o modelo configurado (Opus para
implementação). O catálogo não garante autorização de uso. GPT usa Responses
estruturado e SSE; Claude usa Messages JSON. Há limites de entrada/saída, timeout e
concorrência. Assinaturas informadas pelo usuário não comprovam custo zero.

avello_smoke mantém o ledger de uma tentativa por provedor/execução. O healthcheck
apenas verifica autenticação, descoberta OAuth/MCP e status: nunca faz inferência.

## Validação

```bash
python -m pip install -r requirements.txt pytest httpx
python -m pytest -q tests
```

Testes OAuth offline cobrem PKCE HTTP, vínculo a cliente/recurso, replay, expiração,
refresh, revogação, CSRF, consentimento, conta autorizada e verificação real de
JWTs OIDC assinados com chaves de teste. Não comprovam login real Google nem
instalação no ChatGPT. A conexão final precisa ser observada no cliente.

