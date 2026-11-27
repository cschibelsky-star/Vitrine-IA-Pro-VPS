# Cópia do workspace do Assessor Online em HML

`assessor_hml_snapshot(confirm="EXECUTAR")` usa o broker local de manutenção. A operação requer o sujeito autorizado e os escopos `projects:read` e `projects:write`. O destino, o projeto e os cinco caminhos são fixos. A resposta traz apenas o nome do arquivo, SHA-256, tamanho e contagem.

O arquivo é privado e fica em `/var/lib/super-v2-maintenance`, criado pelo systemd. O broker reabre o arquivo e compara as entradas e seus bytes antes de disponibilizá-lo. Há limite de 20 cópias e de 2 MiB por arquivo. A operação falha se algum arquivo estiver ausente, for simbólico ou mudar durante a leitura. Esta cópia cobre os cinco arquivos, sem incluir banco, volumes, `.env` ou o índice Git.

Para habilitar na HML, a instalação controlada do broker no host precisa incluir `assessor_snapshot.py` junto de `maintenance_broker.py` e a unidade systemd atualizada. O contêiner MCP também precisa ser reconstruído com `operational_mcp.py` e `maintenance_client.py` do mesmo commit. Após a atualização dos dois componentes, verificar se a ferramenta aparece no catálogo autenticado, invocá-la e registrar o hash e a contagem. A restauração deve ser ensaiada em um diretório separado antes de atualizar o workspace original.

Validação local: `python -m unittest -v test_assessor_snapshot test_maintenance_broker` passou com 10 testes. `python -m py_compile operational_mcp.py` também passou. O teste cria e lê um arquivo de cópia com dados fictícios. A instalação do broker, a descoberta MCP e a cópia do workspace real continuam pendentes.
