# Centro Operacional v2 — Política de Autonomia

## Objetivo

Permitir desenvolvimento, auditoria, homologação, backup, testes, build e preparação de publicação sem interrupções por confirmação a cada operação, preservando bloqueios para ações irreversíveis ou de produção.

## Escopo inicial

- `/srv/tvsumare`
- `/srv/backups/tvsumare`
- `/srv/vitrine/docker/nginx/conf.d`
- `/srv/vitrine/docker/nginx/html`
- `/srv/vitrine/ssl` somente por operações específicas de certificado
- `/srv/connectors/vitrine-vps-mcp` somente por fluxo versionado de atualização do próprio conector

## Nível A — automático

Sem confirmação adicional:

- inventário, leitura, busca e logs;
- criação de workspace e diretórios permitidos;
- escrita e patch em homologação;
- Git status, diff, log, branch, fetch e clone;
- lint, testes e validação de sintaxe;
- build de containers de homologação;
- start, stop e restart de containers de homologação;
- criação e atualização de virtual host de homologação;
- `nginx -t`;
- reload do gateway somente após `nginx -t` aprovado;
- backup antes de substituição;
- geração de ZIP e release;
- emissão e renovação de certificado de homologação;
- importação do HostGator para área de staging, sem apagar origem.

## Nível B — automático com backup e rollback

- substituição de arquivos versionados;
- sincronização incremental para homologação;
- atualização de dependências;
- mudança de configuração não sensível;
- restauração de release anterior;
- migrations não destrutivas em homologação.

Requisitos obrigatórios:

1. backup automático;
2. auditoria em JSONL;
3. validação antes da aplicação;
4. rollback definido;
5. segredos redigidos na saída.

## Nível C — confirmação explícita

- deploy definitivo em produção;
- alteração de DNS;
- troca ou revogação de credenciais;
- alteração de firewall;
- exclusão de dados ou volumes;
- migration destrutiva;
- `git reset --hard`, `git clean`, force push;
- remoção de containers com dados persistentes;
- desligamento do HostGator;
- alteração do domínio principal.

## Operações específicas

O conector deve expor operações declarativas, em vez de shell irrestrito:

- `tvsumare_workspace_create`
- `tvsumare_import_hostgator_snapshot`
- `tvsumare_git_status`
- `tvsumare_write_file`
- `tvsumare_apply_patch`
- `tvsumare_run_tests`
- `tvsumare_build_homologation`
- `tvsumare_start_homologation`
- `tvsumare_container_status`
- `tvsumare_create_nginx_vhost`
- `tvsumare_nginx_test`
- `tvsumare_nginx_reload`
- `tvsumare_issue_certificate`
- `tvsumare_create_release_zip`
- `tvsumare_rollback_homologation`
- `tvsumare_prepare_production_cutover`

## Segurança

- caminhos resolvidos e confinados a roots autorizados;
- bloqueio de `.env`, chaves privadas e tokens nas respostas;
- sem `bash -c` genérico;
- argumentos validados por operação;
- timeout e limite de saída;
- auditoria obrigatória;
- idempotência sempre que aplicável;
- produção separada de homologação.

## Migração da TV Sumaré

O primeiro uso do Centro Operacional v2 será:

1. preservar HostGator;
2. criar `/srv/tvsumare`;
3. importar aplicação e dados para staging;
4. criar containers `tvsumare_app` e `tvsumare_web`;
5. publicar `tv-hml.vitrineiapro.com.br`;
6. validar aplicação completa;
7. preparar `tvsumare.com.br` sem alterar DNS;
8. executar cutover somente com autorização explícita.
