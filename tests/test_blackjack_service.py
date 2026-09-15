from qqbot_app.blackjack_service import BlackjackService, parse_blackjack_command
from qqbot_app.providers import AnswerContext


def _context(conversation_id: str = "group:1") -> AnswerContext:
    return AnswerContext(event_type="onebot_group_at", extra={"conversation_id": conversation_id})


def _command(text: str):
    command = parse_blackjack_command(text)
    assert command is not None
    return command


def test_player_blackjack_pays_three_to_two() -> None:
    service = BlackjackService(deck_factory=lambda: ["7", "10", "K", "A"])

    answer = service.handle("u1", _command("21点 下注：10"), _context())

    assert "Blackjack 获胜（+15）" in answer
    assert "本局虚拟盈亏：+15" in answer


def test_dealer_ten_upcard_blackjack_is_revealed_immediately() -> None:
    service = BlackjackService(deck_factory=lambda: ["A", "10", "8", "10"])

    answer = service.handle("u1", _command("21点"), _context())

    assert "庄家拥有 Blackjack！" in answer
    assert "庄家 Blackjack（-1）" in answer


def test_insurance_offsets_dealer_blackjack_loss() -> None:
    service = BlackjackService(deck_factory=lambda: ["K", "A", "8", "8"])
    prompt = service.handle("u1", _command("21点 下注：10"), _context())
    answer = service.handle("u1", _command("买保险"), _context())

    assert "买保险" in prompt
    assert "庄家拥有 Blackjack！" in answer
    assert "保险下注 +5：+10" in answer
    assert "本局虚拟盈亏：0" in answer


def test_hit_bust_and_game_is_cleared() -> None:
    service = BlackjackService(deck_factory=lambda: ["K", "7", "9", "6", "10"])
    service.handle("u1", _command("开始21点"), _context())

    answer = service.handle("u1", _command("要牌"), _context())

    assert "你爆牌了。" in answer
    assert "第 1 手：10、6、K（26 点），爆牌（-1）" in answer
    assert "当前没有进行中的 21 点牌局" in service.handle("u1", _command("停牌"), _context())


def test_double_draws_once_then_stands() -> None:
    service = BlackjackService(deck_factory=lambda: ["K", "6", "9", "6", "10"])
    service.handle("u1", _command("21点"), _context())

    answer = service.handle("u1", _command("加倍"), _context())

    assert "已加倍，并自动停牌。" in answer
    assert "第 1 手：10、6、K（26 点），爆牌（-2）" in answer


def test_split_plays_each_hand_and_settles_separately() -> None:
    service = BlackjackService(deck_factory=lambda: ["5", "6", "3", "8", "8", "8"])
    service.handle("u1", _command("21点"), _context())
    split = service.handle("u1", _command("分牌"), _context())
    first = service.handle("u1", _command("停牌"), _context())
    answer = service.handle("u1", _command("停牌"), _context())

    assert "已分成两手" in split
    assert "当前第 2 手" in first
    assert "第 1 手：8、6（14 点）" in answer
    assert "第 2 手：8、5（13 点）" in answer


def test_surrender_loses_half_wager_without_dealer_draw() -> None:
    service = BlackjackService(deck_factory=lambda: ["K", "6", "9", "6", "10"])
    service.handle("u1", _command("21点 下注：10"), _context())

    answer = service.handle("u1", _command("投降"), _context())

    assert "投降（-5）" in answer
    assert "本局虚拟盈亏：-5" in answer


def test_soft_ace_score_and_dealer_stands_on_soft_seventeen() -> None:
    service = BlackjackService(deck_factory=lambda: ["A", "6", "7", "A"])
    start = service.handle("u1", _command("21点"), _context())
    answer = service.handle("u1", _command("停牌"), _context())

    assert "A、7（18 点）" in start
    assert "庄家的牌：6、A（17 点）" in answer


def test_group_game_allows_only_starter_and_keeps_sessions_isolated() -> None:
    service = BlackjackService(deck_factory=lambda: ["K", "7", "9", "6", "10"])
    service.handle("u1", _command("21点"), _context("group:1"))

    assert service.handle("u2", _command("要牌"), _context("group:1")) == "当前牌局只能由开局玩家操作。"
    assert "当前没有进行中的" in service.handle("u2", _command("要牌"), _context("group:2"))


def test_parse_blackjack_commands() -> None:
    assert _command("21 点").action == "start"
    assert _command("21点 下注：12").wager == 12
    assert _command("继续要牌").action == "hit"
    assert _command("加倍").action == "double"
    assert _command("分牌").action == "split"
    assert _command("投降").action == "surrender"
    assert _command("买保险").action == "insurance_yes"
    assert _command("不买保险").action == "insurance_no"
    assert parse_blackjack_command("21点怎么玩") is None
