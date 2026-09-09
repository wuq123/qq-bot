from pathlib import Path

import yaml

from qqbot_app.auth_service import AuthService, parse_auth_command


def test_owner_user_ids_initialize_and_persist(tmp_path: Path) -> None:
    path = tmp_path / "auth.yaml"

    service = AuthService(path, ["owner-1", "owner-2"])

    assert service.get_role("owner-1", "notes") == "owner"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["owners"] == ["owner-1", "owner-2"]


def test_load_yaml_permissions(tmp_path: Path) -> None:
    path = tmp_path / "auth.yaml"
    path.write_text(
        "owners:\n- owner-1\nfeatures:\n  notes:\n    admin-1: admin\n    user-1: user\n",
        encoding="utf-8",
    )

    service = AuthService(path)

    assert service.get_role("owner-1", "notes") == "owner"
    assert service.get_role("admin-1", "notes") == "admin"
    assert service.get_role("user-1", "notes") == "user"


def test_same_user_can_have_different_feature_roles(tmp_path: Path) -> None:
    path = tmp_path / "auth.yaml"
    service = AuthService(path, ["owner-1"])

    service.grant("owner-1", "u1", "notes", "user")
    service.grant("owner-1", "u1", "tasks", "guest")

    assert service.get_role("u1", "notes") == "user"
    assert service.get_role("u1", "tasks") == "guest"


def test_owner_can_grant_any_role(tmp_path: Path) -> None:
    service = AuthService(tmp_path / "auth.yaml", ["owner-1"])

    answer = service.grant("owner-1", "u1", "notes", "admin")

    assert answer == "已设置用户 u1 在 notes 功能的身份为 admin。"
    assert service.get_role("u1", "notes") == "admin"


def test_admin_can_only_grant_user_or_guest_for_same_feature(tmp_path: Path) -> None:
    service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    service.grant("owner-1", "admin-1", "notes", "admin")

    allowed_answer = service.grant("admin-1", "u1", "notes", "user")
    rejected_answer = service.grant("admin-1", "u2", "notes", "admin")
    other_feature_answer = service.grant("admin-1", "u3", "tasks", "user")

    assert allowed_answer == "已设置用户 u1 在 notes 功能的身份为 user。"
    assert rejected_answer == "你没有权限设置该功能权限。"
    assert other_feature_answer == "你没有权限设置该功能权限。"


def test_user_guest_and_unknown_cannot_grant(tmp_path: Path) -> None:
    service = AuthService(tmp_path / "auth.yaml", ["owner-1"])
    service.grant("owner-1", "user-1", "notes", "user")
    service.grant("owner-1", "guest-1", "notes", "guest")

    assert service.grant("user-1", "u1", "notes", "user") == "你没有权限设置该功能权限。"
    assert service.grant("guest-1", "u1", "notes", "user") == "你没有权限设置该功能权限。"
    assert service.grant("unknown", "u1", "notes", "user") == "无法识别用户身份，已拒绝权限操作。"


def test_parse_auth_commands() -> None:
    grant = parse_auth_command("设置权限 用户：u1 功能：notes 身份：user")
    describe = parse_auth_command("查看权限 用户：u1")
    me = parse_auth_command("查看我的ID")

    assert grant is not None
    assert grant.action == "grant"
    assert grant.target_user_id == "u1"
    assert grant.feature == "notes"
    assert grant.role == "user"
    assert describe is not None
    assert describe.action == "describe"
    assert describe.target_user_id == "u1"
    assert me is not None
    assert me.action == "me"
