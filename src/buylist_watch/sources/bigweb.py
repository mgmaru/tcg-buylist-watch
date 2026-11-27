"""BIG-WEB。

買取のページ（/ja/purchase/pokemon/list）が読み込んでいるJSONを、100件ずつ順に取得する。
is_purchase=1 のときの price が買取価格。販売価格は別の一覧（約34,000件）なので取得しない。
買取価格は「状態A」相当での値段。
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator

from ..http import Fetcher
from ..models import Price

NAME = "bigweb"
LABEL = "BIG-WEB"
LINK = ("BIG-WEBの買取で探す", "https://www.bigweb.co.jp/ja/purchase/pokemon/list?name={name}")
API_URL = "https://api.bigweb.co.jp/products?game_id=170&is_purchase=1&page={page}"

_BRACKET = re.compile(r"【([^】]*)】")
_HEAD = re.compile(r"^[(（]([^()（）]*)[)）]\s*(\S.*)$")  # 名前の先頭の (…)
_TAIL = re.compile(r"^(.*\S)\s*(?:[(（]([^()（）]*)[)）]|【([^【】]*)】)$")  # 名前の末尾の (…) や 【…】
# 名前の末尾の (…) のうち、カードの仕様を表す言葉。これ以外（ボスの指令(ゲーチス) など）は名前の一部として残す
_SPEC = re.compile(r"仕様|ミラー|柄|キラ|スペシャルアート|復刻|未開封|Lv\.|ロゴ|シンボル|デザイン|チャンピオン|ショップ|セット|付|版|※|^[A-Z]{1,3}$")
_NUMBER = re.compile(r"^\s*[(（]([^()（）]*)[)）]")  # comment の先頭の (134/103)
_STATE = re.compile(r"【(状態[^】]*|NM)】")
_RARITY = re.compile(r"^(.*?)[(（]([^()（）]*)[)）]$")  # TD(キラ)、 - (ミラー)


def split_name(raw: str) -> tuple[str, list[str]]:
    """「トウコ(モンスターボール柄)」「カイリュー【Lv.45】」を (名前, 仕様の言葉) に分ける。

    ほかの店は「ボスの指令(ゲーチス)」の人名や「ルガルガン(まよなかのすがた)」の姿を名前に含めているので、
    仕様を表す言葉だけを名前から外す。
    """
    name, words = raw.strip(), []
    if (m := _HEAD.match(name)) and _SPEC.search(m.group(1)):  # (未開封)名探偵ピカチュウ
        name, words = m.group(2), [m.group(1).strip()]
    tail = 0  # 末尾から外した言葉の数。もとの並び順のまま words に入れるために数える
    while m := _TAIL.match(name):
        word = (m.group(2) or m.group(3) or "").strip()
        if m.group(3) is None and not _SPEC.search(word):
            break
        name = m.group(1)
        if word:
            words.insert(len(words) - tail, word)
            tail += 1
    return name, words


def set_code(fname_tokens: list[str], slip: str) -> str:
    """パックの記号。

    商品名の側（【sI】）と分類の側（【sI/sN】）の両方に書いてある。分類の側のほうがパックの記号として
    そろっているので基本はそちらを使い、分類が複数のパックをまとめているときだけ商品名の側を使う。
    """
    m = _BRACKET.match(slip.strip())
    packs = m.group(1).split("/") if m else []
    for token in fname_tokens:
        if token in packs:
            return token
    return m.group(1) if m else ""


def parse_item(item: dict) -> Price:
    name, words = split_name(item.get("name") or "")
    fname = item.get("fname") or ""
    tokens = [t.strip() for t in _BRACKET.findall(fname)]
    if "1ED" in tokens:
        words.append("1ED")
    rest = _BRACKET.sub("", fname).strip()
    if m := re.fullmatch(r"[(（]([^()（）]*)[)）]", rest):  # (マスターボール柄ミラー)、(未開封)
        words.append(m.group(1).strip())
    rarity = ((item.get("rarity") or {}).get("web") or "").strip()
    if m := _RARITY.match(rarity):
        rarity = m.group(1)
        words.append(m.group(2).strip())
    comment = item.get("comment") or ""
    number = _NUMBER.match(comment)
    if m := _STATE.search(comment):
        words.append(m.group(1))
    variant: list[str] = []
    for word in words:
        # 同じことを言っている言葉（「マスターボール柄」と「マスターボール柄ミラー」）は、長いほうだけ残す
        if not any(word in kept for kept in variant):
            variant = [kept for kept in variant if kept not in word] + [word]
    return Price(
        item_id=str(item["id"]),
        name=name,
        variant=" ".join(variant),
        set_code=set_code([t for t in tokens if t != "1ED"], (item.get("cardset") or {}).get("slip") or ""),
        number=number.group(1).strip() if number else "",
        rarity=rarity.strip(" -"),
        buy_price=int(item.get("price") or 0),
    )


def parse(raw: bytes) -> tuple[list[Price], int]:
    """1ページぶんのJSONから (価格の一覧, 最終ページ番号) を返す。"""
    doc = json.loads(raw)
    if "items" not in doc or "pagenate" not in doc:
        raise ValueError("items か pagenate がありません。JSONの形が変わった可能性があります")
    return [parse_item(i) for i in doc["items"]], int(doc["pagenate"].get("pageCount") or 1)


def fetch(fetcher: Fetcher, max_pages: int | None = None) -> Iterator[Price]:
    page, last = 1, 1
    while page <= last and (max_pages is None or page <= max_pages):
        prices, last = parse(fetcher.get(API_URL.format(page=page)))
        yield from prices
        page += 1
