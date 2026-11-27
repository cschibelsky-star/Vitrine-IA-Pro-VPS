# Backup do banco SQLite na HML

O catálogo anuncia `project_hml_database_backup` somente para `assessor-online-pr137-current-hml`. A chamada exige `projects:read`, `projects:write` e `confirm=EXECUTAR`.

O broker usa o contêiner registrado e confere rótulos Compose, volume local, origem e destino do mount. O caminho esperado usa o diretório padrão do Docker em `/var/lib/docker/volumes`. Se a instalação usar caminho diferente ou se o usuário do broker não puder ler o volume, a operação falha sem ampliar permissões. A instalação no host deve incluir `hml_sqlite_backup.py` com os demais módulos do broker.

A cópia usa a API de backup do SQLite, em modo de leitura na origem, e valida a integridade antes de publicar. Retorna metadados, tamanho e SHA-256. O arquivo fica privado em `/var/lib/super-v2-maintenance`. Há limite de cinco cópias, 128 MiB de páginas e um orçamento de tempo para a cópia e validação.

A verificação foi executada em banco fictício com WAL. Na VPS, confirmar acesso ao volume e recuperar a cópia em diretório isolado antes de confiar nela para retorno. Bancos do Cockpit, outras aplicações e operações de atualização e retorno são etapas separadas.
