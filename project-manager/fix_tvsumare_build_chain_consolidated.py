from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path

REPO = Path('/srv/tvsumare/repository')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')


def backup(path: Path) -> Path:
    dst = path.with_name(f'{path.name}.backup-build-chain-{STAMP}')
    shutil.copy2(path, dst)
    return dst


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f'SKIP_ALREADY_OK={label}')
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: marcador count={count}; abortando antes de gravar')
    print(f'PATCH={label}')
    return text.replace(old, new, 1)


def patch_social(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    old = '''ds_patch($code,
"if(\\$selected && ds_social_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';",
"if(\\$selected && ds_social_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine=(\\$caption!=='' && \\$hashtags!=='')?'revisado':'automatico';",
'Social reviewed copy');'''
    new = '''ds_patch($code,
"\\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';",
"\\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine=(\\$caption!=='' && \\$hashtags!=='')?'revisado':'automatico';",
'Social reviewed copy');'''
    return replace_once(text, old, new, 'social.reviewed_copy')


def patch_queue(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    old = '''"if(\\$action==='send_heygen'){ \\$idx=null; [\\$job,\\$jobs]=rpia_find_videojob(\\$_POST['job_id']??'',\\$idx); if(!\\$job) \\$err='Roteiro não encontrado.'; else { \\$r=rpia_heygen_create(\\$job,\\$cfg); if(!\\$r['ok']) { \\$jobs[\\$idx]['status']='heygen_falhou'; \\$jobs[\\$idx]['technical_error']=substr((string)(\\$r['error']??''),0,1200); \\$jobs[\\$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',\\$jobs); \\$err=rpia_friendly_error('send',\\$r['error']??''); } else {",'''
    new = '''"if(\\$action==='send_heygen'){ \\$idx=null; [\\$job,\\$jobs]=rpia_find_videojob(\\$_POST['job_id']??'',\\$idx); if(!\\$job) \\$err='Roteiro não encontrado.'; elseif((\\$job['status']??'')!=='roteiro_aprovado') \\$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; else { \\$r=rpia_heygen_create(\\$job,\\$cfg); if(!\\$r['ok']) { \\$jobs[\\$idx]['status']='heygen_falhou'; \\$jobs[\\$idx]['technical_error']=substr((string)(\\$r['error']??''),0,1200); \\$jobs[\\$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',\\$jobs); \\$err=rpia_friendly_error('send',\\$r['error']??''); } else {",'''
    text = replace_once(text, old, new, 'reporter_queue.source_with_approval_guard')

    old2 = '''"if(\\$action==='send_heygen'){ \\$idx=null; [\\$job,\\$jobs]=rpia_find_videojob(\\$_POST['job_id']??'',\\$idx); if(!\\$job) \\$err='Roteiro não encontrado.'; elseif(rpia_provider_blocked(\\$cfg)) \\$err=rpia_friendly_error('credits','provider_blocked'); elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c');'''
    new2 = '''"if(\\$action==='send_heygen'){ \\$idx=null; [\\$job,\\$jobs]=rpia_find_videojob(\\$_POST['job_id']??'',\\$idx); if(!\\$job) \\$err='Roteiro não encontrado.'; elseif((\\$job['status']??'')!=='roteiro_aprovado') \\$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; elseif(rpia_provider_blocked(\\$cfg)) \\$err=rpia_friendly_error('credits','provider_blocked'); elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c');'''
    text = replace_once(text, old2, new2, 'reporter_queue.target_preserves_approval_guard')
    return text


def patch_dedup(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    old = '''$old="elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c'); \\$jobs[\\$idx]['status']='enviado'; rpia_write('videos_ia.json',\\$jobs);";'''
    new = '''$old="elseif((\\$job['status']??'')!=='roteiro_aprovado') \\$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c'); \\$jobs[\\$idx]['status']='enviado'; rpia_write('videos_ia.json',\\$jobs);";'''
    text = replace_once(text, old, new, 'reporter_dedup.source_preserves_approval_guard')

    old2 = '''$new="elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; elseif(!rpia_is_current_ready_job(\\$job,\\$jobs)) \\$err='Existe uma versão mais recente desta pauta. Atualize a fila antes de enviar.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c');'''
    new2 = '''$new="elseif((\\$job['status']??'')!=='roteiro_aprovado') \\$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; elseif(rpia_job_state(\\$job)!=='ready' || !empty(\\$job['heygen_session_id']) || !empty(\\$job['heygen_video_id'])) \\$err='Este roteiro já foi enviado ou não está em estado válido para nova geração.'; elseif(!rpia_is_current_ready_job(\\$job,\\$jobs)) \\$err='Existe uma versão mais recente desta pauta. Atualize a fila antes de enviar.'; else { \\$jobs[\\$idx]['send_lock_at']=date('c');'''
    text = replace_once(text, old2, new2, 'reporter_dedup.target_preserves_approval_guard')
    return text


def main() -> None:
    targets = {
        'social': REPO / 'docker/apply-social-distribution-hardening.php',
        'queue': REPO / 'docker/apply-reporter-queue-hardening.php',
        'dedup': REPO / 'docker/apply-reporter-dedup-hardening.php',
    }
    for path in targets.values():
        if not path.is_file():
            raise SystemExit(f'Arquivo ausente: {path}')

    originals = {name: path.read_text(encoding='utf-8') for name, path in targets.items()}
    patched = {
        'social': patch_social(targets['social']),
        'queue': patch_queue(targets['queue']),
        'dedup': patch_dedup(targets['dedup']),
    }

    if all(patched[name] == originals[name] for name in targets):
        print('TVSUMARE_BUILD_CHAIN_ALREADY_COMPATIBLE')
        return

    backups = {}
    for name, path in targets.items():
        if patched[name] != originals[name]:
            backups[name] = backup(path)

    for name, path in targets.items():
        if patched[name] != originals[name]:
            path.write_text(patched[name], encoding='utf-8')

    print('TVSUMARE_BUILD_CHAIN_CONSOLIDATED_PATCHED')
    for name, path in backups.items():
        print(f'BACKUP_{name.upper()}={path}')
    print('TOUCHED=hardening scripts only; admin PHP files unchanged')
    print('NEXT=python3 project-manager/audit_tvsumare_build_chain.py')


if __name__ == '__main__':
    main()
