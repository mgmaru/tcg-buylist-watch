"""トレコロ（CBトレコロの買取）。

買取のトップページ（/shop/c/c2074/）から「買取リスト」のページ（/shop/e/…：超強化買取、SAR、プロモ・高額、
BW・XY など）を見つけ、それぞれを100件ずつ順に読む。全部で約100ページ、約6,000件。

パックごとの一覧をすべてたどれば全カードが取れるが、ほとんどが買取0円の行で、ポケカ全体では数百ページになる。
買取価格の順に並べる方法もない（並び替えは販売価格にしか効かない）ので、店が買取リストに載せているカード
だけを読む。リストに載っていないカードは、買い取っていても記録されない。

名前・レアリティは全角の英数字で書かれているので、半角にそろえて記録する。
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Iterator

from ..http import Fetcher
from ..models import Price

NAME = "torecolo"
LABEL = "トレコロ"
LINK = ("トレコロの買取で探す", "https://www.torecolo.jp/shop/goods/search.aspx?ct2=2074&search=x&keyword={name}")
BASE = "https://www.torecolo.jp"
TOP_URL = BASE + "/shop/c/c2074/"

_LIST = re.compile(r'href="(/shop/e/[A-Za-z0-9]+)/?"')
_TOTAL = re.compile(r"([\d,]+)\s*件あります")
_GOODS = re.compile(r'href="/shop/g/g([^/"]+)/"[^>]*class="js-enhanced-ecommerce-goods-name"[^>]*>([^<]*)</a>')
_RARITY = re.compile(r'block-thumbnail-t--goods-category[^>]*>([^<]*)<')
_BUY = re.compile(r"purchaseprice-title[^>]*>[^<]*</span>\s*([\d,]+)\s*円")
_TAIL = re.compile(r"^(.*\S)\s*(?:\[([^\[\]]*)\]|\(([^()]*)\)|【([^【】]*)】)$")  # 名前の末尾の […]、(…)、【…】
_HEAD = re.compile(r"^([^()\[\]【】]{1,8})\)\s*(\S.*)$")  # 「ミラー版)基本悪エネルギー」「上)ダークライ&クレセリアLEGEND」
# かっこの中が人名で、それも含めてカードの名前になっているもの。ほかの店も名前に含めている
_NAMED = {"ボスの指令", "博士の研究", "ジムバッジ"}


def parse_code(code: str) -> tuple[str, str]:
    """商品コードから (型番, セット) を読む。読めない形なら空文字を返す。

    101-086-SV11W-B-S → 101/086, SV11W    001-165-SV2A-BM1-S → 001/165, SV2A
    217-XY-P-S        → 217/XY-P, XY-P    SM-P009-S          → 009/SM-P, SM-P
    PC-KK1-071-128-S  → 071/128, KK1      013-PLAY-S         → 013/PLAY, PLAY
    """
    body = code[:-2] if code.endswith("-S") else code
    if m := re.fullmatch(r"(\d{3}[a-z]?)-(\d{3})-([A-Za-z0-9+]+)(?:-.*)?", body):
        return f"{m.group(1)}/{m.group(2)}", m.group(3)
    if m := re.fullmatch(r"PC-([A-Za-z0-9+]+)-(\d{3})-(\d{3})(?:-\d)?", body):
        return f"{m.group(2)}/{m.group(3)}", m.group(1)
    if m := re.fullmatch(r"(\d{3})-([A-Za-z]+-P|PLAY)\d?", body):
        return f"{m.group(1)}/{m.group(2)}", m.group(2)
    if m := re.fullmatch(r"([A-Za-z]+-P)(\d{3})", body):
        return f"{m.group(2)}/{m.group(1)}", m.group(1)
    return "", ""


def split_name(raw: str) -> tuple[str, str]:
    """「フシギダネ[ミラー仕様][マスターボール柄]」を (名前, 仕様) に分ける。"""
    name, words = unicodedata.normalize("NFKC", raw).strip(), []
    if m := _HEAD.match(name):
        name, words = m.group(2), [m.group(1).strip()]
    tail = 0
    while m := _TAIL.match(name):
        if m.group(1) in _NAMED:
            break  # ボスの指令[ゲーチス] の人名は名前の一部
        word = next(g for g in m.groups()[1:] if g is not None).strip()
        name = m.group(1)
        if word:
            words.insert(len(words) - tail, word)
            tail += 1
    return name, " ".join(words)


def parse_page(page: str) -> tuple[list[Price], int, int | None]:
    """1ページぶんのHTMLから (買取価格のある商品, 商品の数, リスト全体の件数) を返す。

    販売の商品（買取価格がない行）は、数には入れるが返さない。件数の表示がないリストは None。
    """
    prices, count = [], 0
    for block in page.split("js-enhanced-ecommerce-item")[1:]:
        goods = _GOODS.search(block)
        if not goods:
            continue
        count += 1
        buy = _BUY.search(block)
        if not buy:
            continue
        name, variant = split_name(html.unescape(goods.group(2)))
        number, set_code = parse_code(goods.group(1))
        rarity = _RARITY.search(block)
        prices.append(Price(item_id=goods.group(1), name=name, variant=variant, set_code=set_code, number=number,
                            rarity=unicodedata.normalize("NFKC", html.unescape(rarity.group(1))).strip() if rarity else "",
                            buy_price=int(buy.group(1).replace(",", ""))))
    total = _TOTAL.search(re.sub(r"<[^>]+>", " ", page))
    return prices, count, int(total.group(1).replace(",", "")) if total else None


def list_paths(top: str) -> list[str]:
    """買取のトップページから、買取リストのページ（/shop/e/…）を見つける。"""
    seen: dict[str, str] = {}
    for path in _LIST.findall(top):
        seen.setdefault(path.lower(), path)  # 大文字・小文字だけが違うリンクは同じページ
    return list(seen.values())


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    paths = list_paths(fetcher.get(TOP_URL).decode("utf-8", errors="replace"))
    if not paths:
        raise ValueError("買取リストのページ（/shop/e/…）が1つも見つかりません。トップページの作りが変わった可能性があります")
    fetched, done = 0, set()
    for path in paths:
        page, count, total = 1, 0, None
        while True:
            if max_pages is not None and fetched >= max_pages:
                return
            url = f"{BASE}{path}/" if page == 1 else f"{BASE}{path}_p{page}/"
            text = fetcher.get(url).decode("utf-8", errors="replace")
            fetched += 1
            prices, seen, seen_total = parse_page(text)
            count, total = count + seen, seen_total if total is None else total
            for p in prices:
                if p.item_id not in done:  # 同じカードが、いくつものリストに載っている
                    done.add(p.item_id)
                    yield p
            if f'{path}_p{page + 1}/"' not in text:
                break
            page += 1
        if total is not None and count != total:
            # 足りないまま保存すると「掲載終了」を誤って記録する
            raise ValueError(f"{path}: 一覧には{total}件とあるのに、読めたのは{count}件です。ページの作りが変わった可能性があります")
