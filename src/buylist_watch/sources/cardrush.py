"""カードラッシュ（ラッシュメディアの買取表）。

公開ページ /pokemon/buying_prices に埋め込まれた __NEXT_DATA__ を読む。
robots.txt が禁止している /api は使わない。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib.parse import urlencode

from ..http import Fetcher
from ..models import Price

NAME = "cardrush"
BASE_URL = "https://cardrush.media/pokemon/buying_prices"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def page_url(page: int) -> str:
    query = {"displayMode": "リスト", "limit": 100, "page": page, "sort[key]": "amount", "sort[order]": "desc"}
    return f"{BASE_URL}?{urlencode(query)}"


def parse_page(html: str) -> tuple[list[Price], int]:
    """1ページぶんのHTMLから (価格の一覧, 最終ページ番号) を返す。"""
    m = _NEXT_DATA.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ が見つかりません。ページの作りが変わった可能性があります")
    props = json.loads(m.group(1))["props"]["pageProps"]
    prices = []
    for row in props["buyingPrices"]:
        product_id = row.get("pokemon_ocha_product_id")
        if product_id is None:
            # 商品IDがない行は、名前と型番で識別する
            item_id = "|".join([row.get("name", ""), row.get("model_number") or "", row.get("extra_difference") or ""])
        else:
            item_id = str(product_id)
        prices.append(
            Price(
                item_id=item_id,
                name=row.get("name", ""),
                variant=row.get("extra_difference") or "",
                set_code=row.get("pack_code") or "",
                number=row.get("model_number") or "",
                rarity=row.get("rarity") or "",
                buy_price=int(row.get("amount") or 0),
                source_updated_at=row.get("updated_at") or "",
            )
        )
    return prices, int(props.get("lastPage") or 1)


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    page, last = 1, 1
    while page <= last and (max_pages is None or page <= max_pages):
        html = fetcher.get(page_url(page)).decode("utf-8", errors="replace")
        prices, last = parse_page(html)
        yield from prices
        page += 1
