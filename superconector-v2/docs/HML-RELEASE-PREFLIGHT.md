# Verificação prévia de atualização na HML

A ferramenta `project_hml_release_preflight` requer somente `projects:read`, projeto registrado e o SHA Git completo de 40 caracteres. Informa o commit do workspace, se há alterações locais, se o commit solicitado existe localmente e quais imagens e contêineres estão em execução. Para o Docker, confere o projeto e o serviço pelos rótulos esperados. A consulta não faz fetch, checkout, build ou alteração de serviço. O commit local não equivale a commit aprovado, publicado ou associado à imagem em execução.

O Assessor Online e o Cockpit têm alterações locais confirmadas no ambiente operacional. A consulta informa o indicador sem expor nomes de arquivos não rastreados. Os IDs das imagens permitem preparar o retorno, mas não garantem retorno se a imagem ou o banco tiverem sido removidos ou alterados.

Para ativar a ferramenta, a instalação do broker no host precisa incluir `hml_release_preflight.py` do mesmo commit dos outros módulos, e o contêiner MCP precisa ser reconstruído. Atualização e retorno automáticos não são capacidades deste PR. Essas operações precisam de imagem candidata e anterior verificadas, configuração original do Compose preservada, backup aplicável e teste funcional por projeto.
