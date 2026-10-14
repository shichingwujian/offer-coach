"""permission 包统一出口：权限闸门。"""

from offer_coach.permission.gate import DEFAULT_RULES, Action, PermissionGate, PermissionRule

__all__ = [
    "DEFAULT_RULES",
    "Action",
    "PermissionGate",
    "PermissionRule",
]
