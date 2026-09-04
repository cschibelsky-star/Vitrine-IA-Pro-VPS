from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path('/srv/connectors/vitrine-vps-mcp')
TARGET = ROOT / 'project_file_operations.py'
STAMP = datetime.now().strftime('%Y%m%d-%H%M%S')

OLD = '''    except OSError:\n        return {\n            "ok": False,\n            "path": relative,\n            "success": False,\n            "exit_code": 127,\n            "stdout": "php_lint_unavailable",\n        }'''

NEW = '''    except OSError:\n        # O broker V3.2 nao precisa carregar PHP. Para a TV Sumare, reutiliza\n        # a imagem PHP homologada do container web e valida o arquivo atual do\n        # workspace em um container efemero, isolado e com mount somente leitura.\n        tvsumare_repository = Path("/srv/tvsumare/repository").resolve()\n        if repository.resolve() != tvsumare_repository:\n            return {\n                "ok": False,\n                "path": relative,\n                "success": False,\n                "exit_code": 127,\n                "stdout": "php_lint_unavailable",\n            }\n\n        try:\n            inspect = run_process(\n                ["docker", "inspect", "--format", "{{.Config.Image}}", "tvsumare_web"],\n                cwd=str(repository),\n                shell=False,\n                text=True,\n                capture_output=True,\n                timeout=timeout,\n                check=False,\n                env={**os.environ, "LC_ALL": "C.UTF-8"},\n            )\n        except (OSError, subprocess.TimeoutExpired):\n            return {\n                "ok": False,\n                "path": relative,\n                "success": False,\n                "exit_code": 127,\n                "stdout": "php_lint_runtime_unavailable",\n            }\n\n        image = inspect.stdout.strip() if inspect.returncode == 0 else ""\n        if not image:\n            return {\n                "ok": False,\n                "path": relative,\n                "success": False,\n                "exit_code": inspect.returncode or 125,\n                "stdout": "php_lint_runtime_image_unavailable",\n            }\n\n        try:\n            proc = run_process(\n                [\n                    "docker", "run", "--rm",\n                    "--network", "none",\n                    "--read-only",\n                    "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",\n                    "--entrypoint", "php",\n                    "-v", f"{repository}:/lint:ro",\n                    image,\n                    "-l", f"/lint/{relative}",\n                ],\n                cwd=str(repository),\n                shell=False,\n                text=True,\n                capture_output=True,\n                timeout=timeout,\n                check=False,\n                env={**os.environ, "LC_ALL": "C.UTF-8"},\n            )\n        except subprocess.TimeoutExpired:\n            return {\n                "ok": False,\n                "path": relative,\n                "success": False,\n                "exit_code": 124,\n                "stdout": "timeout",\n            }\n        except OSError:\n            return {\n                "ok": False,\n                "path": relative,\n                "success": False,\n                "exit_code": 127,\n                "stdout": "php_lint_runtime_unavailable",\n            }\n\n        output = _sanitize_lint_output(\n            proc.stdout + proc.stderr,\n            repository,\n            target,\n            relative,\n        )\n        success = proc.returncode == 0\n        return {\n            "ok": success,\n            "path": relative,\n            "success": success,\n            "exit_code": proc.returncode,\n            "stdout": output,\n            "runtime": "tvsumare_web_image",\n            "runtime_image": image,\n        }'''


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f'Arquivo nao encontrado: {TARGET}')

    text = TARGET.read_text(encoding='utf-8')
    if NEW in text:
        print('V32_TVSUMARE_PHP_LINT_ALREADY_PATCHED')
        return
    if OLD not in text:
        raise RuntimeError('Bloco php_lint_unavailable esperado nao encontrado; nenhuma alteracao aplicada')

    backup = TARGET.with_name(f'{TARGET.name}.backup-tvsumare-php-lint-{STAMP}')
    shutil.copy2(TARGET, backup)
    TARGET.write_text(text.replace(OLD, NEW, 1), encoding='utf-8')

    print('V32_TVSUMARE_PHP_LINT_PATCHED')
    print(f'BACKUP={backup}')
    print('NEXT=python3 -m py_compile project_file_operations.py')
    print('NEXT=docker compose -f docker-compose.mcp.yml up -d --build')


if __name__ == '__main__':
    main()
