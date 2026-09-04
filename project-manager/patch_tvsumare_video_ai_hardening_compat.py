from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path('/srv/tvsumare/repository/docker/apply-video-ai-hardening.php')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

LABEL = "'Reporter send');"

REPLACEMENT = r'''patch_one($reporter,
"if(\$action==='send_heygen'){ \$idx=null; [\$job,\$jobs]=rpia_find_videojob(\$_POST['job_id']??'',\$idx); if(!\$job) \$err='Roteiro não encontrado.'; elseif((\$job['status']??'')!=='roteiro_aprovado') \$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; else { \$r=rpia_heygen_create(\$job,\$cfg); if(!\$r['ok']) \$err=\$r['error']; else {",
"if(\$action==='send_heygen'){ \$idx=null; [\$job,\$jobs]=rpia_find_videojob(\$_POST['job_id']??'',\$idx); if(!\$job) \$err='Roteiro não encontrado.'; elseif((\$job['status']??'')!=='roteiro_aprovado') \$err='Revise e aprove o roteiro antes de enviar ao HeyGen.'; else { \$r=rpia_heygen_create(\$job,\$cfg); if(!\$r['ok']) { \$jobs[\$idx]['status']='heygen_falhou'; \$jobs[\$idx]['technical_error']=substr((string)(\$r['error']??''),0,1200); \$jobs[\$idx]['updated_at']=date('c'); rpia_write('videos_ia.json',\$jobs); \$err=rpia_friendly_error('send',\$r['error']??''); } else {",
'Reporter send');'''


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    text = TARGET.read_text(encoding='utf-8')
    lines = text.splitlines()

    label_indexes = [i for i, line in enumerate(lines) if line.strip() == LABEL]
    if len(label_indexes) != 1:
        raise RuntimeError(f'Reporter send label count={len(label_indexes)}; nenhuma alteracao aplicada')

    idx = label_indexes[0]
    start = idx - 3
    if start < 0 or lines[start].strip() != 'patch_one($reporter,':
        raise RuntimeError('Bloco Reporter send inesperado; nenhuma alteracao aplicada')

    current_block = '\n'.join(lines[start:idx + 1])
    if "roteiro_aprovado" in current_block and "rpia_friendly_error('send'" in current_block:
        print('TVSUMARE_VIDEO_AI_HARDENING_ALREADY_COMPATIBLE')
        return

    backup = TARGET.with_name(f'{TARGET.name}.backup-approval-compat-{STAMP}')
    shutil.copy2(TARGET, backup)

    new_lines = lines[:start] + REPLACEMENT.splitlines() + lines[idx + 1:]
    TARGET.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')

    print('TVSUMARE_VIDEO_AI_HARDENING_COMPAT_PATCHED')
    print(f'BACKUP={backup}')
    print('PRESERVED=roteiro_aprovado guard')
    print('NEXT=php -l docker/apply-video-ai-hardening.php (or project_php_lint)')
    print('NEXT=project_compose_manage tvsumare up')


if __name__ == '__main__':
    main()
