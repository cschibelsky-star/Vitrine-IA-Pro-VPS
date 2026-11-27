# Catálogo de projetos HML

A operação de preservação aceita apenas o identificador do projeto. Raiz e arquivos são definidos no broker, por projeto. O cliente verifica a identidade do destino retornado. O catálogo de leitura informa somente operações implementadas e registradas.

Os primeiros projetos são Assessor Online e Cockpit. A cobertura é limitada aos cinco e dois arquivos registrados, respectivamente, identificados na consulta do Git em 27/11/2026. Verifique alterações adicionais no Git antes de considerar a cópia suficiente. O backup não contém banco, volumes, segredos de ambiente ou estado da imagem. O diretório privado e o formato de verificação são os do PR #118.

## Instalação do piloto

Instalar no broker do host `maintenance_broker.py`, `hml_projects.py` e `assessor_snapshot.py` do mesmo commit, com a unidade systemd do PR #118. A imagem operacional precisa ser reconstruída para incorporar `operational_mcp.py` e `maintenance_client.py`. Após a instalação, conferir o catálogo autenticado e verificar uma cópia de cada projeto. O arquivo retornado é privado e pode ser conferido e recuperado em pasta separada por um operador da VPS.

## Aceite restante

Banco e volumes exigem procedimentos por projeto. O Assessor Online usa SQLite em volume Docker. Antes de automatizar uma atualização do Cockpit, confirmar a configuração efetivamente usada no contêiner e como preservar suas alterações locais. A especificação do serviço no catálogo é informativa e não habilita operação Docker.

Ainda faltam backup do banco, atualização de uma revisão específica, retorno, teste real de SSO e envio único via Titan. O piloto não altera o fluxo do Assessor Online ou do Cockpit ao criar a cópia.
