# TV Sumaré: inventário HeyGen em runtime

## Estado
Correção preparada; não instalada nem homologada na VPS. Sem merge, deploy, reinício, geração paga ou alteração de credenciais.

## Contrato
GET /tvsumare/heygen/runtime-inventory?environment=production
Usa a autenticação existente do router. Aceita apenas production e homologation, mapeados a tvsumare_web_prod e tvsumare_web. Retorna identidade do container/imagem, hashes SHA-256 e nomes conhecidos de endpoints em sete arquivos fixos. Nunca retorna código, IDs HeyGen, parâmetros, variáveis de ambiente ou stderr bruto.

O scanner usa php -n -r, lê texto e tokeniza; não inclui nem executa o PHP da aplicação. Não chama a rede nem o provedor. O resultado é inventário estático dos pontos conhecidos, não prova de tráfego efetivo nem varredura exaustiva. Arquivo ausente torna o resultado incompleto.

## Instalação controlada pendente
1. Confirmar diretório e revisão do runtime do conector; preservar alterações locais e backup dos módulos/registro.
2. Incluir heygen_runtime_audit.py no pacote/imagem do ops_broker ao lado de tvsumare_operations.py. Aplicar apenas o diff revisado desse módulo, preservando extensões operacionais existentes.
3. Aplicar a função cliente tvsumare_heygen_runtime_inventory ao módulo instalado tvsumare_tools.py, sem substituir o arquivo por uma cópia histórica.
4. No único main.py MCP, importar essa função como _tvsumare_heygen_runtime_inventory e registrar wrapper com annotations readOnlyHint=True e destructiveHint=False. Não criar outro FastMCP.
5. Homologar router autenticado (401 sem token), registro MCP único, scanner PHP e leitura da imagem HML; validar que nenhuma saída contém secrets.
6. Recriar somente os serviços do conector necessários, após homologação e com rollback. Não reiniciar TV Sumaré.
7. Executar inventário de produção e comparar os hashes com a revisão conhecida antes de concluir a auditoria HeyGen.

## Validação realizada
Seis testes unitários com subprocess mock passaram em 20/10/2026: alvos fixos, entrada inválida sem execução, projeção de saída, rejeição de paths/endpoints inesperados, incompletude e supressão de erros sensíveis. Compilação Python passou. Sem Docker/PHP local: scanner real e instalação dependem da homologação acima.

## Rollback
Restaurar módulos e registro preservados e recriar somente o conector. Não alterar imagem, volumes ou configuração da aplicação TV Sumaré.
