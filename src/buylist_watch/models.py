from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Price:
    """1店・1商品ぶんの価格。

    item_id はその店の中で日をまたいで変わらない識別子。
    sell_price は店の販売価格で、取得元が出していなければ None。
    """

    item_id: str
    name: str
    variant: str  # 1ED、未開封、色違い など。なければ空文字
    set_code: str
    number: str  # 069/090 のような型番
    rarity: str
    buy_price: int
    sell_price: int | None = None
    source_updated_at: str = ""


CSV_FIELDS = [f.name for f in fields(Price)]
