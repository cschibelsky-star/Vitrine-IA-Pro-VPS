from __future__ import annotations

import main as core

# main.py is the single registry for V5 tools. Keeping this entrypoint thin
# prevents duplicate FastMCP tool names and the resulting internal errors.
mcp = core.mcp


if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
