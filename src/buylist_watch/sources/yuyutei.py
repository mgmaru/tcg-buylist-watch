"""遊々亭。

買取と販売の検索結果ページ（検索語なし）を順にたどって読む。1ページに600件並ぶ。
扱いはBWシリーズ以降で、古いシリーズは載っていない。
在庫切れの商品にも販売価格が出ているが（高額品は上限の値で並ぶ）、その値段では買えないので、
販売価格は在庫があるものだけ記録する。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator

from ..http import Fetcher
from ..models import Price

NAME = "yuyutei"
BUY_URL = "https://yuyu-tei.jp/buy/poc/s/search?search_word=&page={page}"
SELL_URL = "https://yuyu-tei.jp/sell/poc/s/search?search_word=&page={page}"

_CARD = re.compile(r"/(?:buy|sell)/poc/card/([a-z0-9_\-]+)/(\d+)\"")
_ALT = re.compile(r'alt="([^"]*)"\s+class="card ')
_NUMBER = re.compile(r'text-center my-2">([^<]*)</span>')
_NAME = re.compile(r"<h4[^>]*>([^<]*)</h4>")
_PRICE = re.compile(r"<strong[^>]*>\s*([\d,]+)\s*円")
_PAGE = re.compile(r"[?&;]page=(\d+)")
_SET_LABEL = re.compile(r'name="vers\[\]" value="([^"]+)"[^>]*>\s*<label[^>]*>\s*\[([^\]]+)\]')
_VARIANT = re.compile(r"^(.+?)\(([^()]*)\)$")


def split_name(raw: str) -> tuple[str, str]:
    """「トゲデマル(番号無し)」を (名前, 仕様) に分ける。"""
    m = _VARIANT.match(raw.strip())
    return (m.group(1).strip(), m.group(2).strip()) if m else (raw.strip(), "")


def parse_page(page: str) -> tuple[list[dict], int, dict[str, str]]:
    """1ページぶんを (カードの一覧, 最後のページ番号, セットの記号) にする。"""
    rows = []
    for block in page.split('class="card-product')[1:]:
        card, name, price = _CARD.search(block), _NAME.search(block), _PRICE.search(block)
        if not (card and name and price):
            continue
        number, alt = _NUMBER.search(block), _ALT.search(block)
        num = html.unescape(number.group(1)).strip() if number else ""
        full = html.unescape(name.group(1)).strip()
        # alt は「097/088 UR MゲンガーEX」の形。型番と名前を除いた残りがレアリティ
        rarity = ""
        if alt:
            rest = html.unescape(alt.group(1)).strip()
            if num and rest.startswith(num):
                rest = rest[len(num):].strip()
            if rest.endswith(full):
                rarity = rest[: -len(full)].strip()
        rows.append({"ver": card.group(1), "cid": card.group(2), "number": num, "name": full,
                     "rarity": rarity, "price": int(price.group(1).replace(",", "")),
                     "in_stock": "sold-out" not in block.split(">", 1)[0]})
    last = max((int(n) for n in _PAGE.findall(page)), default=1)
    return rows, last, dict(_SET_LABEL.findall(page))


def _walk(fetcher: Fetcher, url: str, max_pages: int | None) -> tuple[dict[tuple[str, str], dict], dict[str, str]]:
    found: dict[tuple[str, str], dict] = {}
    labels: dict[str, str] = {}
    page, last = 1, 1
    while page <= last and (max_pages is None or page <= max_pages):
        rows, seen_last, seen_labels = parse_page(fetcher.get(url.format(page=page)).decode("utf-8", "replace"))
        if not rows:
            break
        last = max(last, seen_last)
        labels.update(seen_labels)
        for r in rows:
            found.setdefault((r["ver"], r["cid"]), r)
        page += 1
    return found, labels


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    buys, labels = _walk(fetcher, BUY_URL, max_pages)
    sells, more = _walk(fetcher, SELL_URL, max_pages)
    labels.update(more)
    for key in list(buys) + [k for k in sells if k not in buys]:
        row = buys.get(key) or sells[key]
        name, variant = split_name(row["name"])
        sell = sells.get(key)
        yield Price(
            item_id=f"{key[0]}/{key[1]}",
            name=name,
            variant=variant,
            set_code=labels.get(key[0], key[0]),
            number=row["number"],
            rarity=row["rarity"],
            buy_price=buys[key]["price"] if key in buys else 0,
            sell_price=sell["price"] if sell and sell["in_stock"] else None,
        )
