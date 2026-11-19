from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

TOTAL = 100


class WeightError(ValueError):
    pass


@dataclass(frozen=True)
class Entry:
    share: int
    pinned: bool
    active: bool


def compute_shares(entries: Sequence[Entry]) -> list[int]:
    result = [e.share if e.active else 0 for e in entries]
    active = [i for i, e in enumerate(entries) if e.active]
    if not active:
        return result

    pinned = [i for i in active if entries[i].pinned]
    free = [i for i in active if not entries[i].pinned]
    pinned_sum = sum(entries[i].share for i in pinned)

    if not free:
        if pinned_sum != TOTAL:
            raise WeightError(
                f"Все активные офферы закреплены, сумма {pinned_sum}% вместо {TOTAL}%. Открепите хотя бы один"
            )
        return result

    remaining = TOTAL - pinned_sum
    if remaining < 0:
        raise WeightError(f"Сумма закреплённых долей {pinned_sum}% больше {TOTAL}%")

    base, extra = divmod(remaining, len(free))
    for n, i in enumerate(free):
        result[i] = base + (1 if n < extra else 0)
    return result


class _Weighted(Protocol):
    share: int
    pinned: bool

    @property
    def is_active(self) -> bool: ...


def rebalance(offers: Sequence[_Weighted]) -> None:
    shares = compute_shares([Entry(o.share, o.pinned, o.is_active) for o in offers])
    for o, share in zip(offers, shares):
        o.share = share
