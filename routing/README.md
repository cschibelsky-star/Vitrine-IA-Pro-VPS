# Vitrine IA Pro — Registro Central de Rotas

Este diretório define o padrão oficial de URLs temporárias e definitivas do ecossistema.

## Padrões

- Homologação de produto/projeto: `<slug>.hml.vitrineiapro.com.br`
- Central de homologação: `hml.vitrineiapro.com.br`
- URL provisória de cliente: `<slug>.cliente.vitrineiapro.com.br`
- Domínio definitivo do cliente: cadastrado como host adicional apontando para o mesmo upstream.

## Regras

1. O container da aplicação deve estar conectado à rede Docker externa `vitrine_net`.
2. Banco de dados e serviços internos não devem ser expostos à `vitrine_net` salvo necessidade técnica validada.
3. O upstream deve usar o nome do container/serviço na `vitrine_net`, nunca porta pública do host.
4. Homologação deve usar HTTPS.
5. Quando o cliente fornecer domínio próprio, a aplicação não é migrada: adiciona-se o novo host ao proxy e define-se a política do provisório (alias ou redirecionamento 301).
6. URLs legadas podem ser mantidas em `legacy_aliases` durante transição.
7. Novas implantações devem ser registradas em `routes.json` antes da publicação externa.

## Estados sugeridos

- `planned`: definido, ainda não implantado.
- `pending_dns_proxy`: aplicação pronta; faltam DNS e/ou proxy/SSL.
- `active`: publicado e operacional.
- `redirect`: host mantido apenas como redirecionamento.
- `disabled`: rota desativada sem remoção histórica.

## Próxima automação

O Factory deverá consumir `routes.json` e gerar/configurar automaticamente DNS, proxy, SSL e healthcheck quando o provedor de DNS/proxy estiver integrado ao Centro Operacional.
