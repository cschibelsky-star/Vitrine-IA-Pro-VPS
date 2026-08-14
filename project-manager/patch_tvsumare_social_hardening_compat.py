from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path('/srv/tvsumare/repository/docker/apply-social-distribution-hardening.php')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

REPLACEMENTS = (
    (
        "if(\\$selected && ds_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';",
        "if(\\$selected && ds_social_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';",
        'Social reviewed copy source',
    ),
    (
        "$ready=array_values(array_filter($videos,\\'ds_ready\\'));",
        "$ready=array_values(array_filter($videos,\\'ds_social_ready\\'));",
        'Social ready filtering source',
    ),
    (
        '<div class=\\"box\\" style=\\"margin-top:14px\\"><h2>Novo envio</h2><?php if(!\\$ready): ?><p>Nenhum vídeo do Repórter IA está pronto no momento.</p><?php else: ?><form method=\\"post\\" class=\\"form\\"><?=tvs_csrf_field()?>',
        '<div class=\\"box\\" style=\\"margin-top:14px\\"><h2>Novo envio</h2><?php if(!\\$ready): ?><p>Nenhum vídeo vertical 9:16 do Repórter IA está pronto no momento.</p><?php else: ?><form method=\\"post\\" class=\\"form\\"><?=tvs_csrf_field()?>',
        'Social heading source',
    ),
)


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    text = TARGET.read_text(encoding='utf-8')
    original = text
    changed = []

    for old, new, label in REPLACEMENTS:
        if new in text:
            continue
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f'{label}: marcador count={count}; nenhuma alteracao aplicada')
        text = text.replace(old, new, 1)
        changed.append(label)

    if text == original:
        print('TVSUMARE_SOCIAL_HARDENING_ALREADY_COMPATIBLE')
        return

    backup = TARGET.with_name(f'{TARGET.name}.backup-social-compat-{STAMP}')
    shutil.copy2(TARGET, backup)
    TARGET.write_text(text, encoding='utf-8')

    print('TVSUMARE_SOCIAL_HARDENING_COMPAT_PATCHED')
    print(f'BACKUP={backup}')
    print('CHANGED=' + ', '.join(changed))
    print('NEXT=project_compose_manage tvsumare up')


if __name__ == '__main__':
    main()
