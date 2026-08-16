from pathlib import Path
import shutil
from datetime import datetime

P=Path('/srv/tvsumare/repository/admin/radar-regional.php')
T=P.read_text(encoding='utf-8')

def rep(old,new,label):
    global T
    c=T.count(old)
    if c==0 and new in T:
        print(f'{label}=ALREADY_APPLIED'); return
    if c!=1: raise RuntimeError(f'{label}:anchor_count={c}')
    T=T.replace(old,new,1); print(f'{label}=PATCHED')

old="""function tvs_radar_discard($cand,$city,$reason){
  $file=dirname(__DIR__).'/data/pautas_descartadas.json';
  $items=tvs_read_json_file($file);
  $items[]=[
    'id'=>uniqid('desc_'),
    'city'=>$city,
    'title'=>$cand['title']??'',
    'url'=>$cand['url']??'',
    'source'=>$cand['source']??'Fonte consultada',
    'reason'=>$reason,
    'created_at'=>date('c')
  ];
  $items=array_slice($items,-200);
  tvs_save_json_file($file,$items);
  if(function_exists('tvs_radar_log_event')) tvs_radar_log_event($cand['title']??'', $cand['source']??'Fonte consultada', $city, 'DESCARTADA', $reason, $cand['url']??'');
}"""
new="""function tvs_radar_discard($cand,$city,$reason){
  $file=dirname(__DIR__).'/data/pautas_descartadas.json';
  $items=tvs_read_json_file($file); if(!is_array($items)) $items=[];
  $row=is_array($cand)?$cand:[];
  $row['original_id']=$cand['id']??'';
  $row['id']=uniqid('desc_');
  $row['city']=$city;
  $row['title']=$cand['title']??'';
  $row['url']=$cand['url']??($cand['source_url']??'');
  $row['source']=$cand['source']??'Fonte consultada';
  $row['reason']=$reason;
  $row['created_at']=date('c');
  $items[]=$row;
  $items=array_slice($items,-500);
  tvs_save_json_file($file,$items);
  if(function_exists('tvs_radar_log_event')) tvs_radar_log_event($row['title'], $row['source'], $city, 'DESCARTADA', $reason, $row['url']);
}"""
rep(old,new,'RADAR_DISCARD_ARCHIVE')

old="""function tvs_discard_many_from_queue($ids){
  $lookup=array_fill_keys($ids,true); $removed=0; $queue=tvs_queue_read(); $new=[];
  foreach($queue as $q){ if(isset($lookup[$q['id']??''])){ $removed++; continue; } $new[]=$q; }
  tvs_queue_save($new); return $removed;
}"""
new="""function tvs_discard_many_from_queue($ids){
  $lookup=array_fill_keys($ids,true); $removed=0; $queue=tvs_queue_read(); $new=[];
  foreach($queue as $q){
    if(isset($lookup[$q['id']??''])){
      $q['discard_origin']='bulk_manual';
      tvs_radar_discard($q,$q['city']??'Região','Descartada manualmente em lote pelo editor.');
      $removed++; continue;
    }
    $new[]=$q;
  }
  tvs_queue_save($new); return $removed;
}"""
rep(old,new,'RADAR_BULK_DISCARD')

old="""  } elseif($action==='discard'){
    $id=$_POST['id']??''; $queue=tvs_queue_read(); $new=[]; foreach($queue as $q){ if(($q['id']??'')!==$id) $new[]=$q; } tvs_queue_save($new); $notice='Matéria descartada.';
"""
new="""  } elseif($action==='discard'){
    $id=$_POST['id']??''; $queue=tvs_queue_read(); $new=[]; $found=null;
    foreach($queue as $q){ if(($q['id']??'')===$id){ $found=$q; continue; } $new[]=$q; }
    if($found){ $found['discard_origin']='manual'; tvs_radar_discard($found,$found['city']??'Região','Descartada manualmente pelo editor.'); tvs_queue_save($new); $notice='Matéria descartada e preservada no Log Editorial.'; }
    else $error='Matéria não encontrada na fila.';
"""
rep(old,new,'RADAR_SINGLE_DISCARD')

old="""if(($_SERVER['REQUEST_METHOD']??'GET')==='POST'){
  $action=$_POST['action']??'';"""
new="""if(($_SERVER['REQUEST_METHOD']??'GET')==='POST'){
  tvs_verify_csrf();
  $action=$_POST['action']??'';"""
rep(old,new,'RADAR_CSRF_VERIFY')

stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
bak=P.with_name(P.name+f'.backup-radar-final-{stamp}')
shutil.copy2(P,bak)
P.write_text(T,encoding='utf-8')
R=P.read_text(encoding='utf-8')
for marker in ["discard_origin']='manual'","discard_origin']='bulk_manual'","tvs_verify_csrf();","array_slice($items,-500)"]:
    if marker not in R: shutil.copy2(bak,P); raise RuntimeError('verification_failed:'+marker)
print('BACKUP='+str(bak))
print('TVSUMARE_RADAR_FINAL_HOTFIX=SIM')
