from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from qqbot_app.providers.base import AnswerContext


@dataclass(frozen=True)
class BlackjackCommand:
    action: str
    wager: int = 1


@dataclass
class BlackjackHand:
    cards: List[str]
    wager: float
    is_split: bool = False
    status: str = "playing"
    can_double: bool = True
    can_split: bool = True


@dataclass
class BlackjackGame:
    player_id: str
    deck: List[str]
    hands: List[BlackjackHand]
    dealer_cards: List[str]
    phase: str = "player"
    current_hand: int = 0
    insurance_wager: float = 0


class BlackjackService:
    def __init__(self, deck_factory: Callable[[], List[str]] | None = None) -> None:
        self._deck_factory = deck_factory or _shuffled_deck
        self._games: Dict[str, BlackjackGame] = {}
        self._dealer_messages: List[str] = []

    def handle(self, user_id: str, command: BlackjackCommand, context: AnswerContext) -> str:
        key = str(context.extra.get("conversation_id") or f"{context.event_type}:{user_id}")
        if command.action == "start":
            return self._start(key, user_id, command.wager)

        game = self._games.get(key)
        if game is None:
            return "当前没有进行中的 21 点牌局。发送“21点”开始游戏。"
        if game.player_id != user_id:
            return "当前牌局只能由开局玩家操作。"
        if command.action == "quit":
            del self._games[key]
            return "已结束本局 21 点，未结算虚拟下注。"
        if game.phase == "insurance":
            return self._insurance(key, game, command.action)
        if command.action == "hit":
            return self._hit(key, game)
        if command.action == "stand":
            return self._stand(key, game)
        if command.action == "double":
            return self._double(key, game)
        if command.action == "split":
            return self._split(game)
        if command.action == "surrender":
            return self._surrender(key, game)
        return "当前操作不可用。"

    def has_game(self, conversation_id: str) -> bool:
        return conversation_id in self._games

    def handle_messages(self, user_id: str, command: BlackjackCommand, context: AnswerContext) -> List[str]:
        self._dealer_messages = []
        answer = self.handle(user_id, command, context)
        return [*self._dealer_messages, answer]

    def _start(self, key: str, user_id: str, wager: int) -> str:
        if key in self._games:
            return "本局 21 点仍在进行中。请继续操作或发送“结束21点”。"
        deck = self._deck_factory()
        hand = BlackjackHand([_draw(deck), _draw(deck)], float(wager))
        game = BlackjackGame(user_id, deck, [hand], [_draw(deck), _draw(deck)])
        self._games[key] = game
        if _is_blackjack(game.dealer_cards) and _card_value(game.dealer_cards[0]) == 10:
            return self._settle_dealer_blackjack(key, game)
        if game.dealer_cards[0] == "A":
            game.phase = "insurance"
            return _insurance_prompt(game)
        if _is_blackjack(hand.cards):
            return self._settle(key, game)
        return _game_status(game)

    def _insurance(self, key: str, game: BlackjackGame, action: str) -> str:
        if action not in {"insurance_yes", "insurance_no"}:
            return "庄家明牌为 A。请发送“买保险”或“不买保险”。"
        if action == "insurance_yes":
            game.insurance_wager = game.hands[0].wager / 2
        if _is_blackjack(game.dealer_cards):
            return self._settle_dealer_blackjack(key, game)
        game.phase = "player"
        if _is_blackjack(game.hands[0].cards):
            return self._settle(key, game)
        prefix = "庄家没有 Blackjack。" if action == "insurance_yes" else "已跳过保险。"
        return f"{prefix}\n{_game_status(game)}"

    def _hit(self, key: str, game: BlackjackGame) -> str:
        hand = self._current_hand(game)
        hand.cards.append(_draw(game.deck))
        hand.can_double = False
        hand.can_split = False
        score = _score(hand.cards)
        if score > 21:
            hand.status = "bust"
            return self._next_hand_or_settle(key, game, "你爆牌了。")
        if score == 21:
            hand.status = "stood"
            return self._next_hand_or_settle(key, game, "本手达到 21 点，自动停牌。")
        return _game_status(game)

    def _stand(self, key: str, game: BlackjackGame) -> str:
        self._current_hand(game).status = "stood"
        return self._next_hand_or_settle(key, game)

    def _double(self, key: str, game: BlackjackGame) -> str:
        hand = self._current_hand(game)
        if not hand.can_double:
            return "加倍只能在当前手尚未要牌时使用。"
        hand.wager *= 2
        hand.cards.append(_draw(game.deck))
        hand.status = "bust" if _score(hand.cards) > 21 else "stood"
        return self._next_hand_or_settle(key, game, "已加倍，并自动停牌。")

    def _split(self, game: BlackjackGame) -> str:
        hand = self._current_hand(game)
        if not hand.can_split or len(hand.cards) != 2 or hand.cards[0] != hand.cards[1]:
            return "分牌仅限当前手最初的两张同点数牌。"
        first, second = hand.cards
        hand.cards = [first, _draw(game.deck)]
        hand.is_split = True
        hand.can_split = False
        new_hand = BlackjackHand([second, _draw(game.deck)], hand.wager, is_split=True, can_split=False)
        game.hands.insert(game.current_hand + 1, new_hand)
        return _game_status(game, "已分成两手，先操作第一手。")

    def _surrender(self, key: str, game: BlackjackGame) -> str:
        hand = self._current_hand(game)
        if hand.is_split or not hand.can_double:
            return "投降仅限首手尚未要牌时使用。"
        hand.status = "surrendered"
        return self._next_hand_or_settle(key, game, "已投降，本手损失一半下注。")

    def _next_hand_or_settle(self, key: str, game: BlackjackGame, prefix: str = "") -> str:
        for index in range(game.current_hand + 1, len(game.hands)):
            if game.hands[index].status == "playing":
                game.current_hand = index
                return _game_status(game, prefix)
        return self._settle(key, game, prefix, announce_dealer=True)

    def _settle_dealer_blackjack(self, key: str, game: BlackjackGame) -> str:
        for hand in game.hands:
            hand.status = "blackjack" if _is_blackjack(hand.cards) else "dealer_blackjack"
        return self._settle(key, game, "庄家拥有 Blackjack！")

    def _settle(self, key: str, game: BlackjackGame, prefix: str = "", announce_dealer: bool = False) -> str:
        active_hands = [hand for hand in game.hands if hand.status in {"playing", "stood"}]
        if active_hands:
            if announce_dealer:
                self._dealer_messages.append(f"庄家翻开暗牌：{_cards(game.dealer_cards)}（{_score(game.dealer_cards)} 点）")
            while _score(game.dealer_cards) < 17:
                card = _draw(game.deck)
                game.dealer_cards.append(card)
                if announce_dealer:
                    self._dealer_messages.append(f"庄家要牌：{card}（{_score(game.dealer_cards)} 点）")
        dealer_score = _score(game.dealer_cards)
        lines = [prefix] if prefix else []
        total_profit = 0.0
        for index, hand in enumerate(game.hands, 1):
            outcome, profit = _hand_outcome(hand, game.dealer_cards, dealer_score)
            total_profit += profit
            lines.append(f"第 {index} 手：{_cards(hand.cards)}（{_score(hand.cards)} 点），{outcome}（{_money(profit)}）")
        if game.insurance_wager:
            insurance_profit = game.insurance_wager * 2 if _is_blackjack(game.dealer_cards) else -game.insurance_wager
            total_profit += insurance_profit
            lines.append(f"保险下注 {_money(game.insurance_wager)}：{_money(insurance_profit)}")
        lines.extend(
            [
                f"庄家的牌：{_cards(game.dealer_cards)}（{dealer_score} 点）",
                f"本局虚拟盈亏：{_money(total_profit)}",
                "发送“21点”或“21点 下注：10”可再开一局。",
            ]
        )
        del self._games[key]
        return "\n".join(lines)

    @staticmethod
    def _current_hand(game: BlackjackGame) -> BlackjackHand:
        return game.hands[game.current_hand]


def parse_blackjack_command(text: str) -> Optional[BlackjackCommand]:
    value = re.sub(r"<@!?\d+>", "", str(text or "")).strip().lower()
    start = re.fullmatch(r"(?:21\s*点|开始\s*21\s*点)(?:\s+下注[:：]\s*(\d+))?", value)
    if start:
        wager = int(start.group(1) or 1)
        return BlackjackCommand("start", wager) if wager > 0 else None
    actions = {
        "要牌": "hit",
        "继续要牌": "hit",
        "停牌": "stand",
        "加倍": "double",
        "分牌": "split",
        "投降": "surrender",
        "买保险": "insurance_yes",
        "不买保险": "insurance_no",
        "结束21点": "quit",
        "结束 21 点": "quit",
        "退出21点": "quit",
        "退出 21 点": "quit",
    }
    action = actions.get(value)
    return BlackjackCommand(action) if action else None


def _shuffled_deck() -> List[str]:
    deck = [card for card in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K") for _ in range(4)]
    random.shuffle(deck)
    return deck


def _draw(deck: List[str]) -> str:
    if not deck:
        deck.extend(_shuffled_deck())
    return deck.pop()


def _card_value(card: str) -> int:
    return 11 if card == "A" else 10 if card in {"10", "J", "Q", "K"} else int(card)


def _score(cards: List[str]) -> int:
    score = sum(_card_value(card) for card in cards)
    aces = cards.count("A")
    while score > 21 and aces:
        score -= 10
        aces -= 1
    return score


def _is_blackjack(cards: List[str]) -> bool:
    return len(cards) == 2 and _score(cards) == 21


def _hand_outcome(hand: BlackjackHand, dealer_cards: List[str], dealer_score: int) -> tuple[str, float]:
    if hand.status == "surrendered":
        return "投降", -hand.wager / 2
    if hand.status == "bust":
        return "爆牌", -hand.wager
    if _is_blackjack(hand.cards) and not hand.is_split and not _is_blackjack(dealer_cards):
        return "Blackjack 获胜", hand.wager * 1.5
    if _is_blackjack(dealer_cards):
        return ("Blackjack 平局", 0.0) if _is_blackjack(hand.cards) else ("庄家 Blackjack", -hand.wager)
    score = _score(hand.cards)
    if dealer_score > 21 or score > dealer_score:
        return "获胜", hand.wager
    if score < dealer_score:
        return "庄家获胜", -hand.wager
    return "平局", 0.0


def _cards(cards: List[str]) -> str:
    return "、".join(cards)


def _money(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:g}"


def _insurance_prompt(game: BlackjackGame) -> str:
    hand = game.hands[0]
    return "\n".join(
        [
            f"你的牌：{_cards(hand.cards)}（{_score(hand.cards)} 点）",
            "庄家明牌：A，暗牌：?",
            f"可发送“买保险”下注 {_money(hand.wager / 2)}，或发送“不买保险”继续。",
        ]
    )


def _game_status(game: BlackjackGame, prefix: str = "") -> str:
    hand = game.hands[game.current_hand]
    lines = [prefix] if prefix else []
    lines.extend(
        [
            f"当前第 {game.current_hand + 1} 手：{_cards(hand.cards)}（{_score(hand.cards)} 点），下注 {_money(hand.wager)}",
            f"庄家明牌：{game.dealer_cards[0]}，暗牌：?",
        ]
    )
    commands = ["要牌", "停牌"]
    if hand.can_double:
        commands.append("加倍")
    if hand.can_split and len(hand.cards) == 2 and hand.cards[0] == hand.cards[1]:
        commands.append("分牌")
    if not hand.is_split and hand.can_double:
        commands.append("投降")
    lines.append("可操作：" + "、".join(commands) + "。")
    return "\n".join(lines)
