"""ドラゴンスター（ネット買取）。

買取サイトの商品一覧（/pokemon-card/product-list、絞り込みなし）を40件ずつ順にたどって読む。
載っているのはネット買取の価格で、店頭の買取価格とは違う。旧裏面やDPなど古いシリーズも載っている。

一覧にパックの名前は出ないので、set_code は空にする（名前の頭に【BW8】のように書いてあるものを除く）。
「SOLDOUT」の印が付いた商品も、商品のページでは同じ値段で買取カートに入れられるので、買取中として扱う。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from urllib.parse import urlencode

from ..http import Fetcher
from ..models import Price

NAME = "dorasuta"
LABEL = "ドラゴンスター"
LINK = ("ドラゴンスターの買取で探す", "https://buy.dorasuta.jp/pokemon-card/product-list?kw={name}")
BASE_URL = "https://buy.dorasuta.jp/pokemon-card/product-list"

_ITEM = re.compile(
    r'<li class="change_hight">\s*<a href="/pokemon-card/product\?pid=(\d+)">\s*([^<]*?)\s*</a>'
    r"\s*<p>\s*([^<]*?)\s*</p>\s*<p>[^<]*</p>\s*</li>\s*<li>\s*([\d,]+)\s*円\s*</li>"
)
_PAGE_MAX = re.compile(r'name="page_max" value="(\d+)"')
_PAGE_NOW = re.compile(r'class="page_num_cur">\s*(\d+)')
# 名前の中の型番。(134/103)、(109/098 SR)、(089/SM-P)、(XY-P) の形。後ろの言葉はレアリティ
_NUMBER = re.compile(r"[(（]\s*(\d+[a-zA-Z]?/[^\s()（）]+|[A-Za-z]+-P)(?:\s+([^()（）]*?))?\s*[)）]")
_GROUP = re.compile(r"[(（]([^()（）]*)[)）]|\[([^\[\]]*)\]|【([^【】]*)】")
_TAIL = re.compile(r"^(.*\S)\s*(?:[(（]([^()（）]*)[)）]|\[([^\[\]]*)\]|【([^【】]*)】)\s*$")  # 末尾の (…)、[…]、【…】
_LEAD_SET = re.compile(r"^【([^【】]*)】\s*")
# 型番より前のかっこのうち、カードの仕様を表す言葉。これ以外（ボスの指令(サカキ) など）は名前の一部として残す
_SPEC = re.compile(
    r"仕様|ミラー|キラ|ホロ|ホイル|枠|縁|背景|表記|ver$|位$|優勝|バトル|CHAMPIONSHIP|LAWSON|トイザらス|東京|シークレット|プロモ"
)
_RARITY_HEAD = re.compile(r"^([A-Z]{1,3})(?:/(.+))?$")  # (C/キラ)、(U)、(SR)
# レアリティの欄に入っているが、レアリティではなく仕様を表す言葉
_SPEC_RARITY = {"ミラー", "ホイル", "30th復刻版", "30thピカチュウ", "旧裏"}


def page_url(page: int) -> str:
    # ページ送りは、検索フォームの送信と同じ形のGETで受け付けている
    return f"{BASE_URL}?" + urlencode({"form400200_mode": "search", "form400200_params[0]": "pager", "form400200_params[1]": page})


def parse_name(raw: str, rarity_label: str) -> tuple[str, str, str, str, str]:
    """「ジラーチ(ミラー/白枠)(090/173)」を (名前, 仕様, セット, 型番, レアリティ) に分ける。

    型番がない商品（古いプロモなど）は、どのかっこが仕様なのか決められないので、名前をそのまま返す。
    """
    text, set_code = raw.strip(), ""
    if m := _LEAD_SET.match(text):
        set_code, text = m.group(1).strip(), text[m.end():]
    rarity = "" if rarity_label in _SPEC_RARITY or rarity_label == "未登録" else rarity_label
    words = [rarity_label] if rarity_label in _SPEC_RARITY else []
    number = _NUMBER.search(text)
    if not number:
        return text, " ".join(words), set_code, "", rarity
    if number.group(2):
        rarity = number.group(2).strip()
    name, before = text[: number.start()], []
    # 型番の前：仕様を表すかっこだけを名前から外す。後ろから順に見て、名前の一部に当たったらやめる
    while m := _TAIL.search(name):
        word = next(g for g in m.groups()[1:] if g is not None).strip()
        head = _RARITY_HEAD.match(word) if m.group(2) is not None else None
        if head:
            rarity, word = head.group(1), (head.group(2) or "").strip()
        elif m.group(2) is not None and not _SPEC.search(word):
            break  # [SA] や 【SC】 はいつも仕様。(…) は言葉を見て決める
        name = m.group(1)
        if word:
            before.insert(0, word)
    # 型番の後ろ：(ミラー/マスターボール)、[SA]、【SC】。すべて仕様
    after = [next(g for g in m.groups() if g is not None).strip() for m in _GROUP.finditer(text[number.end():])]
    variant: list[str] = []
    for word in words + before + after:
        # 同じことを言っている言葉（「ミラー」と「ミラー/マスターボール」）は、長いほうだけ残す
        if word and not any(word in kept for kept in variant):
            variant = [kept for kept in variant if kept not in word] + [word]
    return name.strip(), " ".join(variant), set_code, number.group(1), rarity


def parse_page(page: str) -> tuple[list[Price], int, int]:
    """1ページぶんのHTMLから (価格の一覧, いまのページ番号, 最終ページ番号) を返す。"""
    last, now = _PAGE_MAX.search(page), _PAGE_NOW.search(page)
    if not last:
        raise ValueError("ページ数（page_max）が見つかりません。ページの作りが変わった可能性があります")
    prices = []
    for pid, raw, rarity_label, price in _ITEM.findall(page):
        name, variant, set_code, number, rarity = parse_name(html.unescape(raw), html.unescape(rarity_label))
        prices.append(Price(item_id=pid, name=name, variant=variant, set_code=set_code, number=number, rarity=rarity,
                            buy_price=int(price.replace(",", ""))))
    return prices, int(now.group(1)) if now else 1, int(last.group(1))


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    page, last = 1, 1
    while page <= last and (max_pages is None or page <= max_pages):
        prices, now, last = parse_page(fetcher.get(page_url(page)).decode("utf-8", errors="replace"))
        if now != page:
            # ページ送りが効かないと、1ページ目を何度も読んで「全件が40件に減った」ことになってしまう
            raise ValueError(f"{page}ページ目を頼んだのに{now}ページ目が返りました。ページ送りの方法が変わった可能性があります")
        if not prices:
            raise ValueError(f"{page}ページ目に商品が1件もありません。ページの作りが変わった可能性があります")
        yield from prices
        page += 1
