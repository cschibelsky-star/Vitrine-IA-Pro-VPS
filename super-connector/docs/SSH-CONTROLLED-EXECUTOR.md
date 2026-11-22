# Super MCP — Executor SSH controlado (proposta v0)

Status: DESIGN / NAO IMPLANTADO. Branch isolada. Nao substitui conectores V5/V4/VPS.

## Objetivo e limites
Disponibilizar ferramentas MCP de leitura e escrita na VPS por SSH, sem terminal irrestrito, sem chave privada exposta ao modelo e sem deploy implicito.

## Arquitetura
ChatGPT -> Super MCP autenticado -> Policy Engine -> Executor SSH -> VPS.
A identidade da sessao, operacao, projeto, caminho e autorizacao devem ser verificadas **no servidor**, nunca apenas no prompt.
A chave SSH fica em secret/volume protegido do servidor MCP, nao em argumentos ou respostas. Usuario SSH dedicado, sem root, com permissoes minimas. Host key pinned em known_hosts; StrictHostKeyChecking=yes; BatchMode=yes; sem agent forwarding.
O executor remoto deve expor subcomandos fixos, e nao aceitar shell arbitrario, operadores de shell, pipelines ou argumentos de comando livres.

## Ferramentas propostas
- ssh_health(): leitura de conectividade, identidade nao sensivel e latencia.
- ssh_project_status(project_id): leitura de estado Git e runtime, sem secrets.
- ssh_read_file(project_id, relative_path, start_line, end_line): leitura apenas de arquivos permitidos; bloquear .env, chaves, credenciais, links simbolicos e escapes de diretorio.
- ssh_list_files(project_id, relative_dir): listagem limitada e paginada.
- ssh_patch_file(project_id, relative_path, expected_sha256, patch, confirm): escrita atomica condicionada ao hash; backup antes de modificar; somente allowlist.
- ssh_run_test(project_id, test_profile, confirm): perfis de teste fixos, sandbox sem rede e sem mutacao em producao.
- ssh_git_diff(project_id): leitura.
- ssh_git_commit(project_id, paths, message, confirm): somente paths permitidos, branch isolada e arvore preservada.

## Controles obrigatorios
1. Registry server-side de project_id -> workspace, ambiente, comandos permitidos, caminhos e permissoes.
2. Negar por padrao producao, secrets, Docker socket, sudo, migrations, deploy, reset, clean, force push, exclusoes e comandos arbitrarios.
3. Mutacoes exigem confirmacao EXECUTAR vinculada a escopo, projeto e operacao; operacoes criticas exigem autorizacao separada.
4. Limites de timeout, tamanho de arquivo, saida, concorrencia e taxa; auditoria sanitizada sem valores secretos.
5. Evitar TOCTOU: validar caminho real, symlinks e hash antes de escrita; rollback testado.
6. Exigir SSH com host key fixa, credencial de menor privilegio e nenhum segredo em logs.
7. Preservar alteracoes locais e exigir Git como fonte de verdade; nao fazer reconciliacao destrutiva.
8. Testes offline obrigatorios: autorizacao, path traversal, symlinks, redacao, falha SSH, host key, atomicidade e rollback.

## Gates de aceite
G0: revisar riscos e contrato de ferramenta.
G1: implementar executor e testes offline isolados.
G2: validar em ambiente SSH de homologacao, com usuario dedicado e credenciais por referencia segura.
G3: comprovar descoberta das ferramentas MCP e chamadas de leitura.
G4: executar escrita de teste em arquivo descartavel explicitamente permitido; confirmar backup e auditoria.
G5: aprovar habilitacao operacional. Sem merge/deploy/producao automaticos.

## Relacao com PR #73
A ferramenta github_actions_dispatch do PR #73 e independente do executor SSH. Nao conceder permissao SSH como atalho para disparo irrestrito de Actions.
