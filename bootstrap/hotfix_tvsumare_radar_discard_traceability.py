from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path('/srv/tvsumare/repository/admin/radar-regional.php')

OLD_RADAR_DISCARD = '''function tvs_radar_discard($cand,$city,$reason){
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
}'''

NEW_RADAR_DISCARD = '''function tvs_radar_discard($cand,$city,$reason){
  $file=dirname(__DIR__).'/data/pautas_descartadas.json';
  $items=tvs_read_json_file($file);
  if(!is_array($items)) $items=[];
  $url=trim((string)($cand['source_url']??($cand['url']??'')));
  $discarded=[
    'id'=>uniqid('desc_'),
    'original_id'=>$cand['id']??'',
    'city'=>$city ?: ($cand['city']??'Região'),
    'category'=>$cand['category']??'Cidade',
    'title'=>$cand['title']??'',
    'subtitle'=>$cand['subtitle']??'',
    'summary'=>$cand['summary']??($cand['description']??''),
    'description'=>$cand['description']??($cand['summary']??''),
    'body'=>$cand['body']??($cand['text']??''),
    'text'=>$cand['text']??($cand['body']??''),
    'url'=>$url,
    'source_url'=>$url,
    'source'=>$cand['source']??'Fonte consultada',
    'image'=>$cand['image']??($cand['image_url']??''),
    'image_credit'=>$cand['image_credit']??'',
    'image_source_type'=>$cand['image_source_type']??'',
    'image_review_required'=>$cand['image_review_required']??0,
    'reason'=>$reason,
    'discard_origin'=>$cand['discard_origin']??'radar',
    'created_at'=>date('c')
  ];
  $items[]=$discarded;
  $items=array_slice($items,-500);
  tvs_save_json_file($file,$items);
  if(function_exists('tvs_radar_log_event')) tvs_radar_log_event($discarded['title'], $discarded['source'], $discarded['city'], 'DESCARTADA', $reason, $url);
}'''

OLD_DISCARD_MANY = '''function tvs_discard_many_from_queue($ids){
  $lookup=array_fill_keys($ids,true); $removed=0; $queue=tvs_queue_read(); $new=[];
  foreach($queue as $q){ if(isset($lookup[$q['id']??''])){ $removed++; continue; } $new[]=$q; }
  tvs_queue_save($new); return $removed;
}'''

NEW_DISCARD_MANY = '''function tvs_discard_many_from_queue($ids){
  $lookup=array_fill_keys($ids,true); $removed=0; $queue=tvs_queue_read(); $new=[];
  foreach($queue as $q){
    if(isset($lookup[$q['id']??''])){
      $q['discard_origin']='bulk_manual';
      tvs_radar_discard($q,$q['city']??'Região','Descartada manualmente em lote pelo editor.');
      $removed++;
      continue;
    }
    $new[]=$q;
  }
  tvs_queue_save($new); return $removed;
}'''

OLD_ACTION = '''  } elseif($action==='discard'){
    $id=$_POST['id']??''; $queue=tvs_queue_read(); $new=[]; foreach($queue as $q){ if(($q['id']??'')!==$id) $new[]=$q; } tvs_queue_save($new); $notice='Matéria descartada.';
  } elseif($action==='save_edit'){'''

NEW_ACTION = '''  } elseif($action==='discard'){
    $id=$_POST['id']??''; $queue=tvs_queue_read(); $new=[]; $discarded=null;
    foreach($queue as $q){
      if(($q['id']??'')===$id){ $discarded=$q; continue; }
      $new[]=$q;
    }
    if($discarded){
      $discarded['discard_origin']='manual';
      tvs_radar_discard($discarded,$discarded['city']??'Região','Descartada manualmente pelo editor.');
      tvs_queue_save($new);
      $notice='Matéria descartada e preservada no Log Editorial.';
    } else {
      $error='Matéria não encontrada na fila; nenhum conteúdo foi removido.';
    }
  } elseif($action==='save_edit'){'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0:
        if new in text:
            print(f'{label}=ALREADY_APPLIED')
            return text
        raise RuntimeError(f'{label}:anchor_not_found')
    if count != 1:
        raise RuntimeError(f'{label}:anchor_not_unique:{count}')
    print(f'{label}=PATCHED')
    return text.replace(old, new, 1)


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f'target_not_found:{TARGET}')

    original = TARGET.read_text(encoding='utf-8')
    updated = replace_once(original, OLD_RADAR_DISCARD, NEW_RADAR_DISCARD, 'RADAR_DISCARD_HELPER')
    updated = replace_once(updated, OLD_DISCARD_MANY, NEW_DISCARD_MANY, 'RADAR_BULK_DISCARD')
    updated = replace_once(updated, OLD_ACTION, NEW_ACTION, 'RADAR_SINGLE_DISCARD')

    if updated == original:
        print('TVSUMARE_RADAR_DISCARD_HOTFIX=ALREADY_APPLIED')
        return 0

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = TARGET.with_name(f'{TARGET.name}.backup-discard-traceability-{stamp}')
    shutil.copy2(TARGET, backup)
    TARGET.write_text(updated, encoding='utf-8')

    # Structural validation without requiring PHP on the host.
    verify = TARGET.read_text(encoding='utf-8')
    required = [
        "'discard_origin'=>'manual'",
        "'discard_origin'=>'bulk_manual'",
        "'source_url'=>$url",
        "'body'=>$cand['body']??($cand['text']??'')",
        "preservada no Log Editorial",
    ]
    missing = [item for item in required if item not in verify]
    if missing:
        shutil.copy2(backup, TARGET)
        raise RuntimeError('verification_failed:' + ','.join(missing))

    print(f'BACKUP={backup}')
    print('TVSUMARE_RADAR_DISCARD_HOTFIX=SIM')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
