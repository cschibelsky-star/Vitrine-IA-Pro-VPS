# Vitrine IA Pro — Hub IA Dev Connector

Este módulo conecta o MCP da VPS ao backend interno do Vitrine IA Hub no Core.

## Ferramentas MCP

- `ai_dev_chat`
- `ai_dev_compare`
- `ai_dev_code_review`
- `ai_dev_models`
- `ai_dev_usage`

## Variáveis obrigatórias no host do conector

```bash
export AI_DEV_HUB_BASE_URL="https://SEU-ENDERECO-DO-CORE"
export AI_DEV_HUB_INTERNAL_TOKEN="TOKEN_INTERNO"
```

O token deve ser o mesmo configurado no Core em `AI_DEV_HUB_INTERNAL_TOKEN`.

## Instalação no VPS

A partir do clone deste repositório:

```bash
cd /caminho/Vitrine-IA-Pro-VPS/connector-v2
python3 install_ai_dev_hub_connector.py
```

O instalador:

1. copia `ai_dev_hub_tools.py` para `/srv/connectors/vitrine-vps-mcp`;
2. registra as cinco ferramentas em `main.py`;
3. adiciona as variáveis do AI Dev Hub ao compose override;
4. cria backups com timestamp antes de alterar arquivos existentes.

Depois, reconstrua/reinicie o conector seguindo o mesmo procedimento operacional já usado pelo Connector V2.

## Segurança

- Não gravar a chave Roteia no conector.
- O conector conhece apenas `AI_DEV_HUB_INTERNAL_TOKEN`.
- A chave Roteia permanece criptografada no Provider Manager do Core.
- As requisições usam `X-Vitrine-Project` quando há um `project_id`.
- O Core aplica allowlist de projetos e limite mensal interno.

## Fluxo

```text
ChatGPT / MCP
    -> AI Dev Hub Connector
    -> /api/internal/ai-dev/* no Core
    -> AiDevHubService
    -> AiHubService
    -> Provider Manager
    -> Roteia
    -> modelo selecionado
```

O conector não duplica roteamento, custos, credenciais ou metering. Essas responsabilidades permanecem no Core.
