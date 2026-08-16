# Vitrine IA Pro — Registro Central de Rotas

Este diretório define o padrão oficial de homologação, URLs provisórias de clientes e domínios definitivos do ecossistema.

## Padrões oficiais

- Central de homologação: `hml.vitrineiapro.com.br`
- Homologação de produto/projeto: `<slug>.hml.vitrineiapro.com.br`
- URL provisória de cliente: `<slug>.cliente.vitrineiapro.com.br`
- Domínio definitivo do cliente: host adicional apontando para o mesmo upstream.

## DNS necessário

Para a topologia atual no VPS `143.95.219.238`, a zona precisa de três registros A:

- `hml.vitrineiapro.com.br` -> `143.95.219.238`
- `*.hml.vitrineiapro.com.br` -> `143.95.219.238`
- `*.cliente.vitrineiapro.com.br` -> `143.95.219.238`

O wildcard `*.hml.vitrineiapro.com.br` não cobre o próprio host `hml.vitrineiapro.com.br`, por isso o registro `hml` é obrigatório separadamente.

Antes de publicar proxy ou emitir SSL, execute:

```bash
python3 routing/dns_preflight.py --expected-ip 143.95.219.238
```

A publicação deve permanecer bloqueada enquanto o preflight retornar código diferente de zero.

## Rede e isolamento

1. Aplicações publicáveis entram na rede Docker externa `vitrine_net`.
2. Banco de dados e serviços internos permanecem fora da `vitrine_net`, salvo exceção técnica formalmente validada.
3. O Nginx frontal acessa o upstream pelo nome do container/serviço na `vitrine_net`; não se publica a porta do banco nem se depende de porta pública do host.
4. Todas as rotas externas usam HTTPS.

## Registro

A fonte declarativa é `routes.json`. Cada nova HML ou implantação provisória deve ser registrada antes da publicação externa.

Campos principais:

- `id`: identificador único da rota;
- `project_id`: projeto/implantação responsável;
- `environment`: `homologation` ou `customer_provisional`;
- `hostname`: host canônico;
- `legacy_aliases`: aliases temporários/legados;
- `upstream`: `container:porta` acessível pela `vitrine_net`;
- `health_path`: endpoint de saúde;
- `ssl`: obrigatório e deve ser `true`;
- `status`: estado operacional.

Estados aceitos na versão 1.0:

- `pending_app`: rota reservada, aplicação ainda não disponível;
- `pending_dns_proxy`: aplicação pronta, aguardando DNS/proxy/SSL;
- `active`: publicada e operacional;
- `disabled`: mantida no histórico, mas não deve ser publicada pelo gerador.

## Validação

```bash
python3 routing/validate_routes.py routing/routes.json
```

O validador bloqueia IDs/hosts duplicados, hostnames fora dos domínios oficiais, upstream inválido, porta fora da faixa, SSL desligado e estados desconhecidos.

## Instalação da Central HML

As credenciais devem existir fora do Git em `/srv/vitrine/secrets/hml-center.env`, com permissão `600`:

```text
HML_CENTER_USER=<usuario>
HML_CENTER_PASSWORD=<senha-forte>
```

Depois execute a partir do checkout da infraestrutura:

```bash
chmod +x routing/install_hml_center.sh
./routing/install_hml_center.sh
```

O instalador valida credenciais, permissões, rede `vitrine_net`, cria backup da instalação anterior, valida `routes.json`, reconstrói a Central HML e exige healthcheck interno positivo.

## Geração Nginx em staging

Fase HTTP/ACME:

```bash
python3 routing/generate_nginx.py routing/routes.json --phase http --output /tmp/vitrine-routing-http
```

Fase HTTPS para uma rota específica:

```bash
python3 routing/generate_nginx.py routing/routes.json --phase https --route-id cursos-ia-hml --output /tmp/vitrine-routing-https
```

O gerador não altera `/srv/vitrine/docker/nginx/conf.d` diretamente. A promoção ao gateway live deve seguir fluxo controlado: validar DNS, gerar staging, backup do vhost anterior, copiar, `nginx -t`, reload, Certbot, promover HTTPS, novo `nginx -t`, reload, healthcheck e rollback em falha.

## Central HML

`routing/hml-center` implementa o painel de `hml.vitrineiapro.com.br`.

- container: `vitrine_hml_center`;
- somente rede `vitrine_net`;
- nenhuma porta do host publicada;
- painel protegido por Basic Auth;
- `HML_CENTER_USER` e `HML_CENTER_PASSWORD` são obrigatórios e nunca devem ser versionados;
- `/health` é o endpoint de monitoramento;
- a interface exibe apenas nome, hostname e estado das HMLs; detalhes internos de infraestrutura não são mostrados.

## Cliente com domínio próprio

Quando o cliente fornecer seu domínio definitivo, a aplicação não é reinstalada. O novo hostname é ligado ao mesmo upstream, recebe SSL próprio e a URL `<slug>.cliente.vitrineiapro.com.br` pode permanecer como alias ou ser convertida em redirecionamento 301 conforme a política comercial/técnica.

## Automação futura

O Centro Operacional/Factory deverá consumir este registro para criar rotas, verificar DNS, publicar Nginx, emitir/renovar SSL e executar healthchecks. Alteração automática de DNS só deve ser habilitada quando o provedor DNS estiver integrado de forma controlada.
