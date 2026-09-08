from __future__ import annotations

from dataclasses import dataclass


READ = "read"
CONTROLLED = "controlled"
CRITICAL = "critical"


@dataclass(frozen=True)
class PolicyRule:
    operation: str
    risk: str
    preservation_required: bool = False
    backup_required: bool = False
    production_guard: bool = False


RULES: dict[str, PolicyRule] = {
    "git_reconcile": PolicyRule("git_reconcile", CONTROLLED),
    "compose_build": PolicyRule("compose_build", CONTROLLED),
    "compose_up": PolicyRule("compose_up", CONTROLLED),
    "git_reset_hard": PolicyRule("git_reset_hard", CRITICAL, preservation_required=True),
    "git_clean": PolicyRule("git_clean", CRITICAL, preservation_required=True),
    "database_restore": PolicyRule("database_restore", CRITICAL, backup_required=True),
    "migration_execute": PolicyRule("migration_execute", CRITICAL, backup_required=True),
    "production_deploy": PolicyRule("production_deploy", CRITICAL, backup_required=True, production_guard=True),
}


def authorize(operation: str, confirm: str = "", production: bool = False) -> dict:
    rule = RULES.get(operation, PolicyRule(operation, READ))
    if rule.risk == READ:
        return {"ok": True, "authorized": True, "risk": READ}
    required = "EXECUTAR PRODUCAO" if (production or rule.production_guard) else "EXECUTAR"
    if confirm != required:
        return {
            "ok": False,
            "authorized": False,
            "error": "authorization_required",
            "operation": operation,
            "risk": rule.risk,
            "required": required,
            "preservation_required": rule.preservation_required,
            "backup_required": rule.backup_required,
        }
    return {
        "ok": True,
        "authorized": True,
        "operation": operation,
        "risk": rule.risk,
        "preservation_required": rule.preservation_required,
        "backup_required": rule.backup_required,
    }


def catalog() -> list[dict]:
    return [
        {
            "operation": rule.operation,
            "risk": rule.risk,
            "preservation_required": rule.preservation_required,
            "backup_required": rule.backup_required,
            "production_guard": rule.production_guard,
        }
        for rule in sorted(RULES.values(), key=lambda item: item.operation)
    ]
