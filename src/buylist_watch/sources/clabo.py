"""カードラボ（オンライン買取）。

買取サイトのシリーズごとの商品一覧を、買取価格の高い順に120件ずつ読む。載っているのは高額カードが中心で、
全部で約1,150件。

キーワード検索（【ポケカ】）でも全シリーズを一度に並べられるが、並び順が決まっておらず、ページをまたぐと
同じ商品が2回出て別の商品が抜ける。シリーズごとの一覧は並び順を指定できるので、こちらを使う。
取りこぼしがないかは、シリーズごとに「一覧に書いてある件数」と「読めた件数」を比べて確かめる。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator

from ..http import Fetcher
from ..models import Price

NAME = "clabo"
LABEL = "カードラボ"
LINK = ("カードラボの買取で探す", "https://www.c-labo-kaitori.jp/product-list?keyword={name}")
LIST_URL = "https://www.c-labo-kaitori.jp/product-list/{series}?num=120&sort=price-desc&page={page}"
# ポケカのシリーズの分類番号。新しいシリーズが始まったら、ここに足す
# （カードラボのポケカのページ https://www.c-labo-kaitori.jp/page/10 から各パックを開くと、パンくずに番号が出る）
SERIES = {927: "MEGA", 645: "スカーレット&バイオレット", 370: "ソード&シールド", 44: "サン&ムーン"}

_CELL = re.compile(r'class="list_item_cell[^"]*list_item_(\d+)"')
_GOODS = re.compile(r'class="goods_name">(.*?)</span>\s*</p>', re.S)
_PRICE = re.compile(r'class="figure">\s*([\d,]+)')
_TOTAL = re.compile(r'class="number">\s*([\d,]+)\s*</span>')
_PAGE = re.compile(r"[?&;]page=(\d+)")
# 例: 《未開封》【ポケカ】ピカチュウex(FUR仕様)【-】PROMO 131/M-P
_TITLE = re.compile(r"^(?P<lead>(?:《[^《》]*》)*)【ポケカ】(?P<name>.+?)【(?P<rarity>[^【】]*)】(?P<set>\S+)\s+(?P<number>\S+)\s*(?P<rest>.*)$")
_TAIL = re.compile(r"^(.*\S)\s*[(（]([^()（）]*)[)）]$")
# 名前の末尾のかっこのうち、仕様を表すもの：「AR仕様」、英数字だけ（YU NAGABA、01/30）。
# これ以外（ボスの指令(ゲーチス)、ゲンガー(グレート) など）は名前の一部として残す
_SPEC = re.compile(r"仕様|^[A-Za-z0-9 ./]+$")
# レアリティの欄に入っているが、レアリティではなく仕様を表す言葉
_SPEC_RARITY = re.compile(r"ミラー|ホイル|キラ")


def page_url(series: int, page: int) -> str:
    return LIST_URL.format(series=series, page=page)


def parse_title(raw: str) -> tuple[str, str, str, str, str]:
    """商品名を (名前, 仕様, セット, 型番, レアリティ) に分ける。形が違えば、名前だけ返す。"""
    m = _TITLE.match(raw.strip())
    if not m:
        return raw.strip().replace("【ポケカ】", "", 1).strip(), "", "", "", ""
    words = re.findall(r"《([^《》]*)》", m.group("lead"))  # 《未開封》
    name, tail = m.group("name").strip(), []
    while t := _TAIL.match(name):
        # 「ボスの指令(カラスバ/SR仕様)」は、人名と仕様が1つのかっこに入っている
        parts = [p.strip() for p in t.group(2).split("/")] if "仕様" in t.group(2) else [t.group(2).strip()]
        spec = [p for p in parts if _SPEC.search(p)]
        if not spec:
            break
        keep = [p for p in parts if p not in spec]
        name = t.group(1) + (f"({'/'.join(keep)})" if keep else "")
        tail = spec + tail
        if keep:
            break
    rarity = m.group("rarity").strip()
    if _SPEC_RARITY.search(rarity):
        words.append(rarity)
        rarity = ""
    words += tail + re.findall(r"[(（]([^()（）]*)[)）]", m.group("rest"))  # (背景:赤)
    return name, " ".join(w for w in words if w), m.group("set"), m.group("number"), rarity.strip(" -")


def parse_page(page: str) -> tuple[list[Price], int, int]:
    """1ページぶんのHTMLから (価格の一覧, そのシリーズの全件数, 最終ページ番号) を返す。"""
    total = _TOTAL.search(page)
    if not total:
        raise ValueError("件数の表示が見つかりません。ページの作りが変わった可能性があります")
    prices = []
    cells = list(_CELL.finditer(page))
    for cell, nxt in zip(cells, cells[1:] + [None]):
        block = page[cell.end(): nxt.start() if nxt else len(page)]
        goods, price = _GOODS.search(block), _PRICE.search(block)
        if not (goods and price):
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", goods.group(1)))
        name, variant, set_code, number, rarity = parse_title(title)
        prices.append(Price(item_id=cell.group(1), name=name, variant=variant, set_code=set_code, number=number,
                            rarity=rarity, buy_price=int(price.group(1).replace(",", ""))))
    last = max((int(n) for n in _PAGE.findall(page)), default=1)
    return prices, int(total.group(1).replace(",", "")), last


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    fetched = 0  # 読んだページの数（全シリーズの合計）
    for series, label in SERIES.items():
        page, last, total, seen = 1, 1, 0, set()
        while page <= last:
            if max_pages is not None and fetched >= max_pages:
                return
            prices, total, seen_last = parse_page(fetcher.get(page_url(series, page)).decode("utf-8", errors="replace"))
            last = max(last, seen_last)
            fetched += 1
            seen.update(p.item_id for p in prices)
            yield from prices
            page += 1
        if len(seen) != total:
            # 並び順がずれて取りこぼしたか、ページの作りが変わった。足りないまま保存すると「掲載終了」を誤って記録する
            raise ValueError(f"{label}シリーズ: 一覧には{total}件とあるのに、読めたのは{len(seen)}件です")
