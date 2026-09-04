from __future__ import annotations

import sys
import types
from pathlib import Path

from marketing_live_patch import apply as apply_marketing_live_patch

main_path = Path('/app/main.py')
if not main_path.is_file():
    raise RuntimeError('main_py_missing')

source = main_path.read_text(encoding='utf-8')
source = apply_marketing_live_patch(source)

core = types.ModuleType('main')
core.__file__ = str(main_path)
sys.modules['main'] = core
exec(compile(source, str(main_path), 'exec'), core.__dict__)

# main.py remains the single registry for V5 tools. The source is patched only
# in memory so the container filesystem can stay read-only.
mcp = core.mcp


if __name__ == '__main__':
    mcp.run(transport='http', host='0.0.0.0', port=8000)
