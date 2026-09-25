# Vitrine IA Pro — Registro Central de Rotas

Este diretório é a fonte de verdade para identidades de deployment e URLs do ecossistema.

## Padrão oficial

### Homologação de projeto

- URL técnica imutável: `p######.hml.vitrineiapro.com.br`
- Alias amigável opcional: `<slug>.hml.vitrineiapro.com.br`

Exemplo:

- `p000001.hml.vitrineiapro.com.br`
- alias: `jarvis.hml.vitrineiapro.com.br`

### Instância de cliente

- URL técnica imutável: `c######.vitrineiapro.com.br`
- Alias amigável opcional: `<slug>.vitrineiapro.com.br`, somente se disponível e não reservado
- Domínio próprio: host adicional apontando para o mesmo upstream

A URL técnica nunca muda quando o projeto, produto ou cliente muda de nome.

## Identidade

- `p` = project/deployment de homologação.
- `c` = customer instance.
- O código possui 6 dígitos e é monotônico.
- O código nunca é reutilizado depois de reservado.
- URLs amigáveis são aliases, nunca identidade técnica.

## Fonte de verdade

`routes.json` é o registry canônico.

Nenhum projeto novo deve inventar hostname diretamente em Docker Compose, Nginx ou Traefik antes de existir no registry.

O provisionador em `provision_route.py` é o único componente autorizado a alocar novos códigos automaticamente.

## Concorrência

O provisionador:

1. adquire lock exclusivo;
2. lê o contador atual;
3. verifica colisões de código, hostname e alias;
4. incrementa o contador;
5. grava o registry em arquivo temporário;
6. substitui o registry de forma atômica.

Isso impede dois deployments concorrentes de receberem o mesmo código.

## Rede e upstream

1. O container publicável deve estar conectado à rede Docker externa `vitrine_net`.
2. Bancos e serviços internos não devem ser publicados nessa rede sem necessidade validada.
3. O upstream usa o nome do container/serviço na `vitrine_net`, nunca porta pública do host.
4. HML e cliente usam HTTPS.
5. DNS, proxy, SSL e healthcheck são etapas posteriores à reserva da identidade.

## Estados

- `planned`: identidade reservada.
- `pending_dns_proxy`: runtime pronto; faltam DNS/proxy/SSL.
- `active`: publicado e saudável.
- `redirect`: host mantido apenas como redirecionamento.
- `disabled`: rota desativada sem reutilizar o código.

## Fluxo Factory

```text
Factory cria deployment
        ↓
provision_route.py / provider
        ↓
reserva p###### ou c######
        ↓
routes.json
        ↓
DNS provider
        ↓
Traefik/proxy
        ↓
SSL
        ↓
healthcheck
        ↓
ACTIVE
```

Aliases amigáveis e domínios próprios nunca alteram a identidade técnica do deployment.
