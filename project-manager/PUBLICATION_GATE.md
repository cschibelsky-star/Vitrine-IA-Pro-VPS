# Gate obrigatório nas atualizações de runtime

O endpoint existente `/projects/clone` atualiza repositórios usados pelo runtime.
Agora consulta o Cockpit **antes** de mkdir, remote reset, fetch, checkout ou pull
em produção. Produção exige target_sha, autorização de uso único e árvore limpa;
checkout fica detached no SHA aprovado, sem pull de uma branch móvel.

Conectar à implementação de `vitrine-ai-pro`, PR técnico sucessor de #92.
As alterações não foram instaladas nos conectores ativos. O installer foi atualizado
para expor target_sha no MCP, mas não foi executado.

Ambiente ausente é desconhecido e bloqueado. Classificar manifests com environment
`homologation` ou `production` após inventário. O piloto `conheca-sumare-prod` não
pode ser liberado por uma classificação errada como homologation.

Configuração privada do broker: PUBLICATION_CONTROL_URL (HTTPS) e
PUBLICATION_EXECUTOR_TOKEN. Não reutilizar o token geral do OPS.
O projeto piloto mapeia para `conheca-sumare` e executor `conheca-sumare-vps`.

A consulta operacional em 09/10/2026 encontrou produção suja e registry apontando
para `visite-sumare`. Essas condições precisam ser reconciliadas e homologadas,
com preservação, antes de uma aprovação. Nenhum estado foi descartado.

A instalação exige também verificar executores de compose, Super/V5/V4 e SSH,
cuja implementação ativa não é demonstrada por este repositório. Este PR não
promete eliminar essas rotas de bypass. Testar a integração em broker isolado
antes de qualquer alteração do plano de controle ativo.

Validação: python3 -m unittest discover -s project-manager -v.
