# ai_work_delegate (HML)

Delegates one bounded task to Claude through the Roteia gateway. HML only, R$ 10 total
cap, one call per `experiment_id`, never retried.

## What the release updater now guarantees

`bootstrap/install_connector_release.py` fails (and rolls back) unless, after the update:

1. the delegate tests pass and the modules compile;
2. `ai_work_delegate` **and** `ai_work_delegate_status` appear in the MCP `tools/list`;
3. `ai_work_delegate_status` reports `ledger.ready = true` through the MCP protocol, meaning
   the ledger directory is a mounted volume, writable, and outside the restorable tree.

## Ledger persistence

The ledger is `/data/ai-work-delegate/ledger.sqlite` in the container, bind-mounted from
`/srv/data/vitrine-ai-work-delegate` on the host (`AI_WORK_DELEGATE_HOST_DIR`). It must stay
outside `/srv/connectors/vitrine-vps-mcp`: the updater backs that tree up and, on failure,
restores the backup, which would roll the ledger back and reset the cap. The installer refuses
a host dir inside the connector root; the tool refuses a ledger under `/app` or the connector root.

## Configuration (environment of the MCP container; unset = blocked)

| Variable | Meaning |
| --- | --- |
| `ROTEIA_API_KEY` | Bearer token. Never written to files by the installer, never returned. |
| `ROTEIA_MODEL_ID` | `provider/model`, must contain `claude`. **Exact id still to be confirmed.** |
| `ROTEIA_PRICE_INPUT_CENTS_PER_MTOK` | BRL cents per million input tokens. **Tariff still to be confirmed.** |
| `ROTEIA_PRICE_OUTPUT_CENTS_PER_MTOK` | BRL cents per million output tokens. |
| `ROTEIA_MAX_OUTPUT_TOKENS` | Optional, 1..4096, default 1024. |

Endpoint is fixed to `https://api.roteia.ai/v1/chat/completions` (host pinned; redirects not followed).
Compose reads these from the environment or the `.env` next to the compose files.

## Cost control

Before reserving budget, the transport computes the worst-case cost (UTF-8 byte length + 64 as
input-token upper bound, plus `max_tokens`, at the configured tariff) and refuses if it exceeds
`max_charge_cents`. A success is recorded as `charge_uncertain` / `pending_verification`: the
ledger has no reconciliation yet, so reserved cents are not released. Reconciling real charges
needs billing evidence from Roteia, which is not defined yet.

## Real-call acceptance (manual, one paid call)

Only after the model id and tariff are configured and `ai_work_delegate_status` shows
`ready_for_paid_call: true`:

```
python /app/acceptance_ai_work_delegate.py --url http://vps_mcp_connector:8765/mcp \
  --experiment-id hml-acceptance-001 --max-charge-cents 100 --confirm EXECUTAR
```

Run it from a one-shot container on the MCP network, as the release probe does. Re-running with
the same experiment id is blocked by the ledger.
