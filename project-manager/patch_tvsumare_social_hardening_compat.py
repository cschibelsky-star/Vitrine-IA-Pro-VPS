from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

TARGET = Path('/srv/tvsumare/repository/docker/apply-social-distribution-hardening.php')
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

OLD_REVIEW = "ds_patch($code,\n\"if(\\$selected && ds_social_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';\",\n\"if(\\$selected && ds_social_ready(\\$selected)){\\n      \\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine=(\\$caption!=='' && \\$hashtags!=='')?'revisado':'automatico';\",\n'Social reviewed copy');"

NEW_REVIEW = "ds_patch($code,\n\"\\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine='manual';\",\n\"\\$caption=trim((string)(\\$_POST['caption']??'')); \\$hashtags=trim((string)(\\$_POST['hashtags']??'')); \\$engine=(\\$caption!=='' && \\$hashtags!=='')?'revisado':'automatico';\",\n'Social reviewed copy');"


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    text = TARGET.read_text(encoding='utf-8')
    if NEW_REVIEW in text:
        print('TVSUMARE_SOCIAL_REVIEW_MATCHER_ALREADY_COMPATIBLE')
        return

    count = text.count(OLD_REVIEW)
    if count != 1:
        raise RuntimeError(f'Social reviewed matcher count={count}; nenhuma alteracao aplicada')

    backup = TARGET.with_name(f'{TARGET.name}.backup-review-matcher-{STAMP}')
    shutil.copy2(TARGET, backup)
    TARGET.write_text(text.replace(OLD_REVIEW, NEW_REVIEW, 1), encoding='utf-8')

    print('TVSUMARE_SOCIAL_REVIEW_MATCHER_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=project_compose_manage tvsumare up')


if __name__ == '__main__':
    main()
