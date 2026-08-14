from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

REPO = Path('/srv/tvsumare/repository')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

SOCIAL = r'''<?php
$path='/var/www/html/admin/distribuicao-social.php';
$code=file_get_contents($path);
if($code===false){fwrite(STDERR,"Distribuição Social não encontrada\n");exit(1);}
function ds_once(&$code,$old,$new,$label){
  if(strpos($code,$new)!==false) return;
  $n=substr_count($code,$old);
  if($n!==1){fwrite(STDERR,"{$label}: trecho esperado count={$n}; abortando\n");exit(2);}
  $code=str_replace($old,$new,$code);
}

ds_once($code,
"function ds_clean(\$v){ return trim(preg_replace('/\\s+/u',' ',strip_tags((string)\$v))); }",
"function ds_clean(\$v){ return trim(preg_replace('/\\s+/u',' ',strip_tags((string)\$v))); }\nfunction ds_status_label(\$s){ return ['aguardando_integracao'=>'Na fila','na_fila'=>'Na fila','processando'=>'Publicando','publicado'=>'Publicado','falhou'=>'Falhou','cancelado'=>'Cancelado'][strtolower((string)\$s)]??ucfirst(str_replace('_',' ',(string)\$s)); }\nfunction ds_queue_active(\$q){ return in_array(strtolower((string)(\$q['status']??'')),['aguardando_integracao','na_fila','processando'],true); }",
'Social helpers');

ds_once($code,
"\$caption=trim((string)(\$_POST['caption']??'')); \$hashtags=trim((string)(\$_POST['hashtags']??'')); \$engine='manual';",
"\$caption=trim((string)(\$_POST['caption']??'')); \$hashtags=trim((string)(\$_POST['hashtags']??'')); \$engine=(\$caption!=='' && \$hashtags!=='')?'revisado':'automatico';",
'Social reviewed copy');

ds_once($code,
"\$duplicate=false; foreach(\$queue as \$q){ if((\$q['video_id']??'')===\$videoId && in_array((\$q['status']??''),['aguardando_integracao','na_fila','processando'],true)){ \$duplicate=true; break; } }",
"\$duplicate=false; foreach(\$queue as \$q){ if((\$q['video_id']??'')===\$videoId && ds_queue_active(\$q)){ \$duplicate=true; break; } }",
'Social idempotency');

if(strpos($code,"array_filter(\$videos,function(\$v) use (\$queue)")===false){
  $old="\$ready=array_values(array_filter(\$videos,'ds_social_ready'));";
  $new="\$ready=array_values(array_filter(\$videos,function(\$v) use (\$queue){ if(!ds_social_ready(\$v)) return false; foreach(\$queue as \$q){ if((\$q['video_id']??'')===(\$v['id']??'') && ds_queue_active(\$q)) return false; } return true; }));";
  ds_once($code,$old,$new,'Social ready filtering');
}

ds_once($code,
"<div class=\"box\" style=\"margin-top:14px\"><h2>Novo envio</h2><?php if(!\$ready): ?><p>Nenhum vídeo vertical 9:16 do Repórter IA está pronto no momento.</p>",
"<div class=\"box\" style=\"margin-top:14px\"><h2>Preparar publicação</h2><?php if(!\$ready): ?><p>Nenhum vídeo pronto aguardando preparação. Vídeos já colocados na fila não aparecem novamente aqui.</p>",
'Social heading');

ds_once($code,
"<?=ds_h(\$q['status']??'')?>",
"<strong><?=ds_h(ds_status_label(\$q['status']??''))?></strong><?php if(!empty(\$q['network_status'])): ?><br><small><?php foreach(\$q['network_status'] as \$net=>\$st): ?><?=ds_h(ucfirst(\$net))?>: <?=ds_h(ds_status_label(\$st))?> <?php endforeach; ?></small><?php endif; ?>",
'Social status UI');

if(file_put_contents($path,$code)===false){fwrite(STDERR,"Falha ao gravar Distribuição Social\n");exit(3);}
echo "SOCIAL_DISTRIBUTION_HARDENING_APPLIED=SIM\n";
'''

QUEUE = r'''<?php
$path='/var/www/html/admin/reporter-ia.php';
$code=file_get_contents($path);
if($code===false){fwrite(STDERR,"Reporter IA não encontrado\n");exit(1);}
function rq_once(&$code,$old,$new,$label){
  if(strpos($code,$new)!==false) return;
  $n=substr_count($code,$old);
  if($n!==1){fwrite(STDERR,"{$label}: trecho esperado count={$n}; abortando\n");exit(2);}
  $code=str_replace($old,$new,$code);
}

$anchor="function rpia_friendly_error(\$context,\$detail=''){ rpia_log_technical_error(\$context,\$detail); \$map=['test'=>'Não foi possível validar a conexão com o provedor de vídeo agora. Tente novamente em alguns instantes.','send'=>'Não foi possível enviar este vídeo para processamento agora. O roteiro foi preservado e pode ser reenviado.','check'=>'Não foi possível atualizar o processamento agora. O estado anterior foi preservado.','failed'=>'O provedor não conseguiu concluir este vídeo. Os detalhes técnicos foram registrados para diagnóstico.']; return \$map[\$context]??'Não foi possível concluir esta operação agora. Os detalhes técnicos foram registrados.'; }";
$helpers="function rpia_friendly_error(\$context,\$detail=''){ rpia_log_technical_error(\$context,\$detail); \$map=['test'=>'Não foi possível validar a conexão com o provedor de vídeo agora. Tente novamente em alguns instantes.','send'=>'Não foi possível enviar este vídeo para processamento agora. O roteiro foi preservado e pode ser reenviado.','check'=>'Não foi possível atualizar o processamento agora. O estado anterior foi preservado.','failed'=>'O provedor não conseguiu concluir este vídeo. Os detalhes técnicos foram registrados para diagnóstico.','credits'=>'Repórter IA indisponível temporariamente — franquia/API sem saldo. Nenhum novo vídeo será enviado até a regularização.']; return \$map[\$context]??'Não foi possível concluir esta operação agora. Os detalhes técnicos foram registrados.'; }\nfunction rpia_is_credit_error(\$detail){ \$d=strtolower((string)\$detail); return strpos(\$d,'insufficient credit')!==false || strpos(\$d,'api credits')!==false || strpos(\$d,'requires \'api\' credits')!==false; }\nfunction rpia_provider_blocked(\$cfg){ return !empty(\$cfg['heygen_send_blocked']); }\nfunction rpia_job_state(\$j){ \$s=strtolower((string)(\$j['status']??'roteiro_pronto')); if(in_array(\$s,['cancelado','cancelled','canceled'],true)) return 'cancelled'; if(in_array(\$s,['heygen_falhou','failed','falhou','erro'],true)) return 'failed'; if(in_array(\$s,['video_pronto','completed','complete','ready','pronto'],true)||!empty(\$j['video_url'])||!empty(\$j['captioned_video_url'])) return 'completed'; if(in_array(\$s,['heygen_agente_processando','processing','enviado','submitted'],true)||!empty(\$j['heygen_session_id'])||!empty(\$j['heygen_video_id'])) return 'processing'; if(in_array(\$s,['publicado','published'],true)) return 'published'; return 'ready'; }\nfunction rpia_state_label(\$state){ return ['ready'=>'Roteiro pronto','processing'=>'Processando','completed'=>'Vídeo pronto','failed'=>'Falhou','cancelled'=>'Cancelado','published'=>'Publicado'][\$state]??'Aguardando'; }";
if(strpos($code,'function rpia_job_state(')===false) rq_once($code,$anchor,$helpers,'Reporter state helpers');

$old="if(\$action==='send_heygen'){ \$idx=null; [\$job,\$jobs]=rpia_find_videojob(\$_POST['job_id']??'',\$idx); if(!\$job) \$err='Roteiro não encontrado.'; elseif((\$job['status']??'')!=='roteiro_aprovado') \$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; else { \$r=rpia_heygen_create(\$job,\$cfg);";
$new="if(\$action==='send_heygen'){ \$idx=null; [\$job,\$jobs]=rpia_find_videojob(\$_POST['job_id']??'',\$idx); if(!\$job) \$err='Roteiro não encontrado.'; elseif((\$job['status']??'')!=='roteiro_aprovado') \$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; elseif(rpia_provider_blocked(\$cfg)) \$err=rpia_friendly_error('credits','provider_blocked'); elseif(rpia_job_state(\$job)!=='ready' || !empty(\$job['heygen_session_id']) || !empty(\$job['heygen_video_id'])) \$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \$jobs[\$idx]['send_lock_at']=date('c'); \$jobs[\$idx]['status']='enviado'; rpia_write('videos_ia.json',\$jobs); \$r=rpia_heygen_create(\$job,\$cfg);";
rq_once($code,$old,$new,'Reporter idempotent send');

$old="\$jobs[\$idx]['status']='heygen_agente_processando'; \$jobs[\$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',\$jobs);";
$new="\$jobs[\$idx]['status']='heygen_agente_processando'; unset(\$jobs[\$idx]['send_lock_at']); \$jobs[\$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',\$jobs);";
rq_once($code,$old,$new,'Reporter unlock after send');

$needle="\$news=array_slice(\$news,0,30); \$jobs=rpia_read('videos_ia.json'); \$callbackUrl=";
$inject="\$news=array_slice(\$news,0,30); \$jobs=rpia_read('videos_ia.json'); \$activeJobs=array_values(array_filter(\$jobs,function(\$j){ return empty(\$j['archived']) && !in_array(rpia_job_state(\$j),['cancelled','failed','published'],true); })); \$historyJobs=array_values(array_filter(\$jobs,function(\$j){ return !empty(\$j['archived']) || in_array(rpia_job_state(\$j),['cancelled','failed','published'],true); })); \$callbackUrl=";
if(strpos($code,'$activeJobs=array_values')===false) rq_once($code,$needle,$inject,'Reporter queue split');

if(file_put_contents($path,$code)===false){fwrite(STDERR,"Falha ao gravar Reporter IA\n");exit(3);}
echo "REPORTER_QUEUE_HARDENING_APPLIED=SIM\n";
'''

DEDUP = r'''<?php
$path='/var/www/html/admin/reporter-ia.php';
$code=file_get_contents($path);
if($code===false){fwrite(STDERR,"Reporter IA não encontrado\n");exit(1);}
function rdh_once(&$code,$old,$new,$label){
  if(strpos($code,$new)!==false) return;
  $n=substr_count($code,$old);
  if($n!==1){fwrite(STDERR,"{$label}: trecho esperado count={$n}; abortando\n");exit(2);}
  $code=str_replace($old,$new,$code);
}

$anchor="function rpia_state_label(\$state){ return ['ready'=>'Roteiro pronto','processing'=>'Processando','completed'=>'Vídeo pronto','failed'=>'Falhou','cancelled'=>'Cancelado','published'=>'Publicado'][\$state]??'Aguardando'; }";
$new="function rpia_state_label(\$state){ return ['ready'=>'Roteiro pronto','processing'=>'Processando','completed'=>'Vídeo pronto','failed'=>'Falhou','cancelled'=>'Cancelado','published'=>'Publicado','superseded'=>'Substituído por versão mais recente'][\$state]??'Aguardando'; }\nfunction rpia_job_dedupe_key(\$j){ \$newsId=trim((string)(\$j['news_id']??'')); if(\$newsId!=='') return 'news:'.\$newsId; \$title=tvs_lower(tvs_clean_text(\$j['title']??'')); \$title=preg_replace('/[^a-z0-9áàâãéêíóôõúç]+/u',' ',\$title); \$title=preg_replace('/\\s+/u',' ',trim((string)\$title)); return \$title!==''?'title:'.\$title:'job:'.(string)(\$j['id']??''); }\nfunction rpia_is_current_ready_job(\$job,\$jobs){ if(rpia_job_state(\$job)!=='ready' || !empty(\$job['archived'])) return false; \$key=rpia_job_dedupe_key(\$job); \$id=(string)(\$job['id']??''); foreach(\$jobs as \$other){ if((string)(\$other['id']??'')===\$id || !empty(\$other['archived'])) continue; if(rpia_job_state(\$other)!=='ready' || rpia_job_dedupe_key(\$other)!==\$key) continue; if((string)(\$other['created_at']??'')>(string)(\$job['created_at']??'')) return false; } return true; }";
if(strpos($code,'function rpia_job_dedupe_key(')===false) rdh_once($code,$anchor,$new,'Reporter dedupe helpers');

$old="elseif(rpia_job_state(\$job)!=='ready' || !empty(\$job['heygen_session_id']) || !empty(\$job['heygen_video_id'])) \$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \$jobs[\$idx]['send_lock_at']=date('c'); \$jobs[\$idx]['status']='enviado'; rpia_write('videos_ia.json',\$jobs);";
$newSend="elseif(rpia_job_state(\$job)!=='ready' || !empty(\$job['heygen_session_id']) || !empty(\$job['heygen_video_id'])) \$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; elseif(!rpia_is_current_ready_job(\$job,\$jobs)) \$err='Existe uma versão mais recente desta pauta. Atualize a fila antes de enviar.'; else { \$jobs[\$idx]['send_lock_at']=date('c'); \$jobs[\$idx]['status']='enviado'; \$jobs[\$idx]['send_attempt_id']=hash('sha256',(string)(\$job['id']??'').'|'.(string)(\$job['created_at']??'')); rpia_write('videos_ia.json',\$jobs);";
rdh_once($code,$old,$newSend,'Reporter latest-only send');

if(file_put_contents($path,$code)===false){fwrite(STDERR,"Falha ao gravar Reporter IA\n");exit(3);}
echo "REPORTER_DEDUP_HARDENING_APPLIED=SIM\n";
'''


def main() -> None:
    files = {
        REPO / 'docker/apply-social-distribution-hardening.php': SOCIAL,
        REPO / 'docker/apply-reporter-queue-hardening.php': QUEUE,
        REPO / 'docker/apply-reporter-dedup-hardening.php': DEDUP,
    }
    for path in files:
        if not path.is_file():
            raise SystemExit(f'Arquivo ausente: {path}')

    backups = []
    for path, content in files.items():
        old = path.read_text(encoding='utf-8')
        if old == content:
            continue
        backup = path.with_name(f'{path.name}.backup-adaptive-{STAMP}')
        shutil.copy2(path, backup)
        backups.append(backup)
        path.write_text(content, encoding='utf-8')

    print('TVSUMARE_BUILD_CHAIN_ADAPTIVE_HARDENINGS_INSTALLED')
    for item in backups:
        print(f'BACKUP={item}')
    print('TOUCHED=3 docker hardening scripts only')
    print('NEXT=python3 project-manager/audit_tvsumare_build_chain.py')


if __name__ == '__main__':
    main()
