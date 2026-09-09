from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, Optional, Set

import yaml

ROLES = {"owner", "admin", "user", "guest"}
USABLE_ROLES = {"owner", "admin", "user"}


@dataclass(frozen=True)
class AuthCommand:
    action: str
    target_user_id: str
    feature: str
    role: str


class AuthService:
    def __init__(self, path: Path, owner_user_ids: Iterable[str] = ()) -> None:
        self._path = path
        self._owners: Set[str] = set()
        self._features: Dict[str, Dict[str, str]] = {}
        self._load()
        original_owners = set(self._owners)
        self._owners.update(user_id.strip() for user_id in owner_user_ids if user_id.strip())
        if self._owners != original_owners:
            self.save()

    def get_role(self, user_id: str, feature: str) -> str:
        if user_id in self._owners:
            return "owner"
        return self._features.get(feature, {}).get(user_id, "guest")

    def can_use(self, user_id: str, feature: str) -> bool:
        return user_id != "unknown" and self.get_role(user_id, feature) in USABLE_ROLES

    def feature_error(self, user_id: str, feature_name: str) -> str:
        if user_id == "unknown":
            return "无法识别用户身份，已拒绝操作。"
        return f"你没有权限使用{feature_name}功能。"

    def grant(self, actor_user_id: str, target_user_id: str, feature: str, role: str) -> str:
        target_user_id = target_user_id.strip()
        feature = feature.strip()
        role = role.strip().lower()
        if actor_user_id == "unknown":
            return "无法识别用户身份，已拒绝权限操作。"
        if not target_user_id:
            return "目标用户不能为空。"
        if not feature:
            return "功能不能为空。"
        if role not in ROLES:
            return "身份只能是 owner、admin、user、guest。"

        actor_role = self.get_role(actor_user_id, feature)
        if actor_role == "owner":
            self._set_role(target_user_id, feature, role)
            self.save()
            return f"已设置用户 {target_user_id} 在 {feature} 功能的身份为 {role}。"
        if actor_role == "admin" and role in {"user", "guest"}:
            self._set_role(target_user_id, feature, role)
            self.save()
            return f"已设置用户 {target_user_id} 在 {feature} 功能的身份为 {role}。"
        return "你没有权限设置该功能权限。"

    def describe(self, user_id: str) -> str:
        if user_id == "unknown":
            return "无法识别用户身份，已拒绝权限操作。"

        lines = [f"用户：{user_id}"]
        if user_id in self._owners:
            lines.append("全局身份：owner")
            lines.append("功能权限：owner 可使用所有功能")
            return "\n".join(lines)

        feature_lines = []
        for feature, users in sorted(self._features.items()):
            role = users.get(user_id)
            if role:
                feature_lines.append(f"- {feature}: {role}")
        if not feature_lines:
            feature_lines.append("- 无（默认 guest）")
        lines.append("全局身份：无")
        lines.append("功能权限：")
        lines.extend(feature_lines)
        return "\n".join(lines)

    def _set_role(self, user_id: str, feature: str, role: str) -> None:
        if role == "owner":
            self._owners.add(user_id)
            return
        self._features.setdefault(feature, {})[user_id] = role

    def _load(self) -> None:
        if not self._path.exists():
            return

        data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        self._owners = {str(user_id).strip() for user_id in data.get("owners", []) if str(user_id).strip()}
        features = data.get("features", {}) or {}
        for feature, users in features.items():
            feature_name = str(feature).strip()
            if not feature_name or not isinstance(users, dict):
                continue
            valid_users = {}
            for user_id, role in users.items():
                user_value = str(user_id).strip()
                role_value = str(role).strip().lower()
                if user_value and role_value in ROLES:
                    valid_users[user_value] = role_value
            if valid_users:
                self._features[feature_name] = valid_users

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "owners": sorted(self._owners),
            "features": {
                feature: dict(sorted(users.items()))
                for feature, users in sorted(self._features.items())
                if users
            },
        }
        self._path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def parse_auth_command(text: str) -> Optional[AuthCommand]:
    value = _strip_mention(text)
    if value in {"查看我的ID", "我的ID", "我的id"}:
        return AuthCommand(action="me", target_user_id="", feature="", role="")
    if value == "查看权限":
        return AuthCommand(action="describe", target_user_id="", feature="", role="")

    describe_match = re.match(r"^查看权限\s+用户[:：]\s*(\S+)\s*$", value)
    if describe_match:
        return AuthCommand(action="describe", target_user_id=describe_match.group(1), feature="", role="")

    grant_match = re.match(r"^设置权限\s+用户[:：]\s*(\S+)\s+功能[:：]\s*(\S+)\s+身份[:：]\s*(\S+)\s*$", value)
    if grant_match:
        target_user_id, feature, role = grant_match.groups()
        return AuthCommand(action="grant", target_user_id=target_user_id, feature=feature, role=role)

    if value.startswith(("设置权限", "查看权限")):
        return AuthCommand(action="invalid", target_user_id="", feature="", role="")
    return None


def _strip_mention(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    return value.strip()
