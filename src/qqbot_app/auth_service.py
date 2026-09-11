from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, Iterable, Optional, Set

import yaml

ROLES = {"owner", "admin", "user", "guest"}
ROLE_RANKS = {"guest": 0, "user": 1, "admin": 2, "owner": 3}
RANK_ROLES = {value: key for key, value in ROLE_RANKS.items()}


@dataclass(frozen=True)
class AuthCommand:
    action: str
    target_user_id: str
    feature: str
    role: str


class FeatureNames:
    def __init__(self, names: Dict[str, str]) -> None:
        self._names = names
        self._feature_by_name = {display_name: feature for feature, display_name in names.items()}

    @classmethod
    def from_file(cls, path: Path) -> "FeatureNames":
        if not path.exists():
            return cls({})
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        features = data.get("features", {}) or {}
        return cls({str(feature): str(display_name) for feature, display_name in features.items()})

    def resolve(self, value: str) -> str:
        text = value.strip()
        return self._feature_by_name.get(text, text)

    def display(self, feature: str) -> str:
        return self._names.get(feature, feature)


class AuthService:
    def __init__(self, path: Path, owner_user_ids: Iterable[str] = (), feature_names: Optional[FeatureNames] = None) -> None:
        self._path = path
        self._owners: Set[str] = set()
        self._features: Dict[str, Dict[str, str]] = {}
        self._feature_names = feature_names or FeatureNames({})
        self._load()
        original_owners = set(self._owners)
        self._owners.update(user_id.strip() for user_id in owner_user_ids if user_id.strip())
        if self._owners != original_owners:
            self.save()

    def get_role(self, user_id: str, feature: str) -> str:
        if user_id == "unknown":
            return "guest"
        if user_id in self._owners:
            return "owner"
        return self._features.get(feature, {}).get(user_id, "user")

    def can_use(self, user_id: str, feature: str) -> bool:
        return self.has_at_least(user_id, feature, "user")

    def has_at_least(self, user_id: str, feature: str, minimum_role: str) -> bool:
        """判断用户是否达到功能最低身份。"""
        if user_id == "unknown":
            return False
        return ROLE_RANKS[self.get_role(user_id, feature)] >= ROLE_RANKS[minimum_role]

    def feature_error(self, user_id: str, feature_name: str) -> str:
        if user_id == "unknown":
            return "无法识别用户身份，已拒绝操作。"
        return f"你没有权限使用{feature_name}功能。"

    def grant(self, actor_user_id: str, target_user_id: str, feature: str, role: str) -> str:
        target_user_id = target_user_id.strip()
        feature = self._feature_names.resolve(feature)
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
            return f"已设置用户 {target_user_id} 在 {self._feature_names.display(feature)} 功能的身份为 {role}。"
        if actor_role == "admin" and role in {"user", "guest"}:
            self._set_role(target_user_id, feature, role)
            self.save()
            return f"已设置用户 {target_user_id} 在 {self._feature_names.display(feature)} 功能的身份为 {role}。"
        return "你没有权限设置该功能权限。"

    def promote(self, actor_user_id: str, target_user_id: str, feature: str) -> str:
        feature = self._feature_names.resolve(feature)
        feature_name = self._feature_names.display(feature)
        if actor_user_id == "unknown":
            return "无法识别用户身份，已拒绝权限操作。"
        if not target_user_id:
            return "请 @ 需要提升权限的用户。"
        if actor_user_id == target_user_id:
            return "不能提升自己的权限。"

        actor_role = self.get_role(actor_user_id, feature)
        actor_rank = ROLE_RANKS[actor_role]
        max_target_rank = actor_rank - 1
        if max_target_rank < ROLE_RANKS["user"]:
            return "你没有权限提升该功能权限。"

        target_role = self.get_role(target_user_id, feature)
        target_rank = ROLE_RANKS[target_role]
        next_rank = target_rank + 1
        if next_rank > max_target_rank:
            return f"用户 {target_user_id} 在 {feature_name} 功能已达到你可提升的最高身份。"

        next_role = RANK_ROLES[next_rank]
        self._set_role(target_user_id, feature, next_role)
        self.save()
        return f"已将用户 {target_user_id} 在 {feature_name} 功能的身份提升为 {next_role}。"

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
                feature_lines.append(f"- {self._feature_names.display(feature)}: {role}")
        if not feature_lines:
            feature_lines.append("- 无（默认 user）")
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

    promote_match = re.match(r"^提升(.+?)权限$", value)
    if promote_match:
        return AuthCommand(action="promote", target_user_id="", feature=promote_match.group(1).strip(), role="")

    if value.startswith(("设置权限", "查看权限", "提升")):
        return AuthCommand(action="invalid", target_user_id="", feature="", role="")
    return None


def _strip_mention(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"<@!?\d+>", "", value)
    value = re.sub(r"@\S+", "", value)
    return value.strip()
