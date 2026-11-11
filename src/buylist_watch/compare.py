"""店をまたいだ比較。ある店の買取価格が、別の店の販売価格より高いカードを探す。

名前と型番だけで突き合わせるので、1EDと再販、通常と色違いのような仕様違いは区別できない。
結果は「候補」であり、買う前に両方の店のページで仕様を確かめること。
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict

from .models import Price

REPORT_FIELDS = [
    "name", "number", "buy_shop", "buy_set", "buy_variant", "buy_price",
    "sell_shop", "sell_set", "sell_variant", "sell_price", "gap", "ratio",
]


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def match_key(p: Price) -> tuple[str, str] | None:
    """突き合わせに使うキー。型番がない商品は誤って一致しやすいので対象外にする。"""
    if not p.number or "/" not in p.number:
        return None
    return norm(p.name), norm(p.number)


def cross_shop(buyers: dict[str, list[Price]], sellers: dict[str, list[Price]], min_buy: int = 3000) -> list[dict]:
    """buyers の買取価格が sellers の販売価格を上回る組み合わせを、差額の大きい順に返す。"""
    by_key: dict[tuple[str, str], list[tuple[str, Price]]] = defaultdict(list)
    for shop, prices in sellers.items():
        for p in prices:
            key = match_key(p)
            if key and p.sell_price:
                by_key[key].append((shop, p))
    rows = []
    for buy_shop, prices in buyers.items():
        for b in prices:
            key = match_key(b)
            if b.buy_price < min_buy or key is None:
                continue
            for sell_shop, s in by_key.get(key, []):
                if sell_shop == buy_shop or s.sell_price >= b.buy_price:
                    continue
                rows.append(
                    {
                        "name": b.name, "number": b.number,
                        "buy_shop": buy_shop, "buy_set": b.set_code, "buy_variant": b.variant, "buy_price": b.buy_price,
                        "sell_shop": sell_shop, "sell_set": s.set_code, "sell_variant": s.variant, "sell_price": s.sell_price,
                        "gap": b.buy_price - s.sell_price, "ratio": round(b.buy_price / s.sell_price, 2),
                    }
                )
    rows.sort(key=lambda r: (-r["gap"], r["name"], r["number"]))
    return rows
