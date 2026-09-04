from __future__ import annotations

from pathlib import Path

from marketing_live_patch import apply as apply_marketing_live_patch

# Temporary startup compatibility fix for the PHP validation runner.
# The copied PHPUnit launcher may lose its executable bit inside the isolated
# tmpfs workspace, so force invocation through the PHP interpreter before the
# V5 registry is imported.
main_path = Path('/app/main.py')
needle = '"tests_marketing": "vendor/bin/phpunit tests/Unit/Marketing --colors=never"'
replacement = '"tests_marketing": "php vendor/bin/phpunit tests/Unit/Marketing --colors=never"'
if main_path.is_file():
    source = main_path.read_text(encoding='utf-8')
    if needle in source:
        source = source.replace(needle, replacement, 1)
    source = apply_marketing_live_patch(source)
    main_path.write_text(source, encoding='utf-8')

import main as core

# main.py is the single registry for V5 tools. Keeping this entrypoint thin
# prevents duplicate FastMCP tool names and the resulting internal errors.
mcp = core.mcp


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
