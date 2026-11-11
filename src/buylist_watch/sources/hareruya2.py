"""晴れる屋2。

買取リストのページ（/pages/buying-list）が読み込んでいるJSONを1回だけ取得する。
販売価格と買取価格の両方が入っている。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from ..http import Fetcher
from ..models import Price

NAME = "hareruya2"
JSON_URL = "https://api.corp.hareruyamtg.com/user_data/hareruya2/json/products_all.json"

# 例: ポニータ:色違い:1ED(C){炎}〈019/090〉[Pt4]
_TITLE = re.compile(r"^(?P<name>.+?)(?:\((?P<rarity>[^()]*)\))?\{[^}]*\}〈(?P<number>[^〉]*)〉\[(?P<set>[^\]]*)\]$")


def parse_title(title: str) -> tuple[str, str, str, str, str]:
    """商品名を (名前, 仕様, レアリティ, 型番, セット) に分ける。形が違えば名前だけ返す。"""
    m = _TITLE.match(title.strip())
    if not m:
        return title.strip(), "", "", "", ""
    name, _, variant = m.group("name").partition(":")
    return name, variant, m.group("rarity") or "", m.group("number"), m.group("set")


def parse(raw: bytes) -> list[Price]:
    doc = json.loads(raw)
    stamp = doc.get("date", "")
    prices = []
    for p in doc["products"]:
        name, variant, rarity, number, set_code = parse_title(p.get("title", ""))
        sell = p.get("sell_price")
        prices.append(
            Price(
                item_id=str(p["id"]),
                name=name,
                variant=variant,
                set_code=set_code,
                number=number if number != "-" else "",
                rarity=rarity,
                buy_price=int(p.get("buy_price") or 0),
                sell_price=int(sell) if sell else None,
                source_updated_at=stamp,
            )
        )
    return prices


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    yield from parse(fetcher.get(JSON_URL))
