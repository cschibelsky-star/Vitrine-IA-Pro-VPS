# Avatar Video Automation V1

## Canonical workflow

`VITRINE / HML / MEDIA / AVATAR_VIDEO / V1`

The Flow layer does not call HeyGen directly. It receives the integration event and delegates avatar-video domain processing to the Vitrine IA Pro Core.

## Flow

`producer -> n8n -> Core /api/internal/media/avatar-video -> HeyGen -> Core callback/status/ledger -> downstream Flow`

## n8n runtime secret

The n8n runtime needs only the Core internal service credential used by this workflow:

- `CENTRO_IA_INTERNAL_TOKEN`

HeyGen credentials remain owned by Core and must not be copied into this workflow.

## Request contract

Required:
- `request_id` (idempotency/event key)
- `project_id`
- `avatar_id`
- `script`

Optional:
- `company_id`
- `voice_id`
- `title`

The Core owns provider selection, HeyGen job persistence, callbacks and credit ledger.
