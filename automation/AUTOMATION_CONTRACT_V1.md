# Automation Contract V1

## Objetivo

Padronizar os eventos entre Core, Factory, n8n e os produtos da Vitrine IA Pro sem acoplar o n8n a Docker, Git ou provisionamento de infraestrutura.

## Evento tenant.provisioned

Produtor: Factory.
Consumidor inicial: n8n.

Payload mínimo:

```json
{
  "event_id": "evt_...",
  "tenant_id": "tenant_...",
  "product": "vitrine-social-midia",
  "status": "provisioned",
  "tenant_url": "https://cliente.vitrineiapro.com.br",
  "admin_url": "https://cliente.vitrineiapro.com.br/admin",
  "company_id": 123,
  "license_id": 456,
  "occurred_at": "2026-09-17T21:00:00-03:00"
}
```

## Idempotência

- `event_id` é obrigatório e imutável.
- O consumidor deve tratar `event_id` como `idempotency_key`.
- Reentregas do mesmo evento não podem provisionar novamente tenant, domínio, licença ou acesso.
- A primeira versão do workflow apenas valida e aceita o evento; persistência de deduplicação será ligada ao Core/registro operacional antes da ativação em produção.

## ERROR_HANDLER V1

O workflow de erro normaliza:
- workflow_name
- workflow_id
- execution_id
- error_message
- failed_at

Ele deve ser associado como error workflow apenas depois de importado e validado no HML.

## Limites arquiteturais

n8n pode:
- orquestrar eventos;
- chamar APIs internas autorizadas;
- enviar notificações;
- executar onboarding e integrações.

n8n não deve:
- manipular Docker diretamente;
- fazer Git checkout/push;
- criar DNS/Traefik sem passar pelo plano de controle;
- executar migrations de forma implícita.

## Ativação

1. importar workflows como drafts;
2. validar sintaxe e nós;
3. associar ERROR_HANDLER V1;
4. testar tenant.provisioned com payload sintético;
5. somente então publicar/ativar.
