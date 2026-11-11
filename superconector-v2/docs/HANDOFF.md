# HANDOFF — Superconector V2

## Ação autorizada
Preparar branch isolada e investigar caminho HML, sem alterar o Super legado, V5, TV Sumaré ou produção.

## Evidência
- Branch: `feature/superconector-v2-hml`.
- Fonte candidata: ZIP HML_Preflight 0.2.0 fornecido na conversa.
- Testes locais: `python -m unittest discover -s tests -q`, 20/20.
- Sem SDK `mcp` local: handshake real não testado.
- Candidato antigo no registry V5 não é a V2.
- A branch contém documentação de preparação, **não o pacote-fonte completo**.

## Riscos que impedem HML
- Não há imagem V2 validada, registro do projeto V2 no V5 nem endpoint HTTPS comprovado.
- O gateway usa `/v1/projects/{project_id}/status` como contrato proposto, não comprovado no V5.
- O plugin de destino público ainda não dispõe de OAuth nativo MCP nem documentação de submissão verificada.

## Próxima entrega controlada
Sincronizar o código do ZIP para branch e revisar Compose/SDK/protocolo, criar HML independente, executar handshake real e revisão de segurança. Não usar o Docker Compose do Super antigo (com mounts privilegiados) como base de deploy.
