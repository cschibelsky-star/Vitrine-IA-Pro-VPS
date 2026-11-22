"""Explicit optional registration for VIA backup MCP functions.

Call register(mcp) only after the authenticated broker routes, read-only backup
mount, isolated writable staging mount and restore policy are validated.
"""
from __future__ import annotations
import os
from typing import Any
from via_backup_mcp_tools import via_backup_verify, via_backup_restore_isolated

def register(mcp: Any) -> bool:
    if os.getenv("VIA_BACKUP_MCP_ENABLED") != "true":
        return False

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def via_backup_verify_integrity(backup_name: str, expected_sha256: str) -> dict:
        """Verify VIA members in a VPS backup without restoring files."""
        return via_backup_verify(backup_name, expected_sha256)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
    def via_backup_restore_to_isolated_staging(backup_name: str, expected_sha256: str) -> dict:
        """Restore only into restricted staging; never modify live VIA."""
        return via_backup_restore_isolated(backup_name, expected_sha256)

    return True
