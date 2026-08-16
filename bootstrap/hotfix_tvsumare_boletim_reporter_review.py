from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/tvsumare/repository/admin')
BOLETIM = ROOT / 'boletim-ia.php'
REPORTER = ROOT / 'reporter-ia.php'


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


def backup(path: Path) -> Path:
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    target = path.with_name(f'{path.name}.backup-review-flow-{stamp}')
    shutil.copy2(path, target)
    print(f'BACKUP={target}')
    return target


def patch_boletim(text: str) -> str:
    text = replace_once(
        text,
        "'script'=>$script,'status'=>'roteiro_pronto','created_at'=>date('c'),'boletim'=>true",
        "'script'=>$script,'status'=>'roteiro_revisao','created_at'=>date('c'),'boletim'=>true",
        'BOLETIM_REVIEW_STATUS',
    )
    text = replace_once(
        text,
        "array_unshift($jobs,$job); bia_write('videos_ia.json',$jobs);",
        "array_unshift($jobs,$job); bia_write('videos_ia.json',$jobs);",
        'BOLETIM_QUEUE_WRITE',
    )
    return text


def patch_reporter(text: str) -> str:
    text = replace_once(
        text,
        "if(($_SERVER['REQUEST_METHOD']??'GET')==='POST'){\n  $action=$_POST['action']??'';",
        "if(($_SERVER['REQUEST_METHOD']??'GET')==='POST'){\n  tvs_verify_csrf();\n  $action=$_POST['action']??'';",
        'REPORTER_CSRF_VERIFY',
    )
    text = replace_once(
        text,
        "if($action==='update_script'){ $idx=null; [$job,$jobs]=rpia_find_videojob($_POST['job_id']??'',$idx); if(!$job) $err='Roteiro não encontrado.'; else { $jobs[$idx]['script']=trim((string)($_POST['script']??'')); $jobs[$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',$jobs); $msg='Roteiro atualizado.'; } }",
        "if($action==='update_script'){ $idx=null; [$job,$jobs]=rpia_find_videojob($_POST['job_id']??'',$idx); if(!$job) $err='Roteiro não encontrado.'; else { $script=trim((string)($_POST['script']??'')); if($script==='') $err='O roteiro não pode ficar vazio.'; else { $jobs[$idx]['script']=$script; $jobs[$idx]['status']='roteiro_aprovado'; $jobs[$idx]['reviewed_at']=date('c'); $jobs[$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',$jobs); $msg='Roteiro revisado e aprovado para envio ao HeyGen.'; } } }",
        'REPORTER_APPROVE_ON_SAVE',
    )
    text = replace_once(
        text,
        "if($action==='send_heygen'){ $idx=null; [$job,$jobs]=rpia_find_videojob($_POST['job_id']??'',$idx); if(!$job) $err='Roteiro não encontrado.'; else { $r=rpia_heygen_create($job,$cfg);",
        "if($action==='send_heygen'){ $idx=null; [$job,$jobs]=rpia_find_videojob($_POST['job_id']??'',$idx); if(!$job) $err='Roteiro não encontrado.'; elseif(($job['status']??'')!=='roteiro_aprovado') $err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; else { $r=rpia_heygen_create($job,$cfg);",
        'REPORTER_HEYGEN_APPROVAL_GUARD',
    )
    text = replace_once(
        text,
        '<button class="btn secondary">Salvar roteiro</button>',
        '<button class="btn secondary">Salvar e aprovar roteiro</button>',
        'REPORTER_APPROVAL_BUTTON',
    )
    return text


def main() -> int:
    for path in (BOLETIM, REPORTER):
        if not path.is_file():
            raise SystemExit(f'target_not_found:{path}')

    boletim_original = BOLETIM.read_text(encoding='utf-8')
    reporter_original = REPORTER.read_text(encoding='utf-8')

    boletim_updated = patch_boletim(boletim_original)
    reporter_updated = patch_reporter(reporter_original)

    boletim_backup = None
    reporter_backup = None
    try:
        if boletim_updated != boletim_original:
            boletim_backup = backup(BOLETIM)
            BOLETIM.write_text(boletim_updated, encoding='utf-8')
        if reporter_updated != reporter_original:
            reporter_backup = backup(REPORTER)
            REPORTER.write_text(reporter_updated, encoding='utf-8')

        bcheck = BOLETIM.read_text(encoding='utf-8')
        rcheck = REPORTER.read_text(encoding='utf-8')
        required = [
            ('boletim_status', "'status'=>'roteiro_revisao'" in bcheck),
            ('reporter_csrf', 'tvs_verify_csrf();' in rcheck),
            ('reporter_approved', "'status']='roteiro_aprovado'" in rcheck),
            ('heygen_guard', "Revise e aprove o roteiro antes de enviar ao HeyGen." in rcheck),
            ('approval_button', 'Salvar e aprovar roteiro' in rcheck),
        ]
        missing = [name for name, ok in required if not ok]
        if missing:
            raise RuntimeError('verification_failed:' + ','.join(missing))
    except Exception:
        if boletim_backup is not None:
            shutil.copy2(boletim_backup, BOLETIM)
        if reporter_backup is not None:
            shutil.copy2(reporter_backup, REPORTER)
        raise

    print('TVSUMARE_BOLETIM_REPORTER_REVIEW_HOTFIX=SIM')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
