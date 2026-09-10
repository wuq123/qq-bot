from types import SimpleNamespace

from qqbot_app.bot_client import _extract_mention_user_ids, _extract_user_id


def test_extract_user_id_from_channel_author_id() -> None:
    message = SimpleNamespace(author=SimpleNamespace(id="channel-user"))

    assert _extract_user_id(message) == "channel-user"


def test_extract_user_id_from_c2c_user_openid() -> None:
    message = SimpleNamespace(author=SimpleNamespace(user_openid="c2c-openid"))

    assert _extract_user_id(message) == "c2c-openid"


def test_extract_user_id_from_group_member_openid() -> None:
    message = SimpleNamespace(author=SimpleNamespace(member_openid="group-member-openid"))

    assert _extract_user_id(message) == "group-member-openid"


def test_extract_user_id_unknown() -> None:
    message = SimpleNamespace(author=SimpleNamespace())

    assert _extract_user_id(message) == "unknown"


def test_extract_mention_user_ids() -> None:
    message = SimpleNamespace(
        mentions=[
            SimpleNamespace(id="channel-user"),
            SimpleNamespace(member_openid="group-user"),
            SimpleNamespace(user_openid="c2c-user"),
        ]
    )

    assert _extract_mention_user_ids(message) == ["channel-user", "group-user", "c2c-user"]
