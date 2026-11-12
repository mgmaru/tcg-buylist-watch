"""店をまたいだ比較。ある店の買取価格が、別の店の販売価格より高いカードを探す。

同じ名前・同じ型番でも、1EDと再販、通常版とミラーは値段がまるで違う別の商品なので、
仕様までそろったものだけを同じカードとして扱う（assign_groups）。
店ごとに仕様の書き方が違うため完全ではない。買う前に両方の店のページで仕様を確かめること。
"""

from __future__ import annotations

import unicodedata
import re
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


# 値段を大きく左右する仕様。店をまたいでも、これが違えば必ず別のカードとして扱う。
# (共通の呼び名, その仕様を表す書き方) を上から順に調べる。同じ組の中では最初に当たったものだけを使う
_HARD_RULES: list[list[tuple[str, str]]] = [
    [("1ED", r"1ED|1st|ファーストエディション"), ("アンリミ", r"アンリミ|再販"), ("初版", r"初版")],
    [
        ("マスターボールミラー", r"マスターボール"),
        ("モンスターボールミラー", r"モンスターボール"),
        ("エネルギーミラー", r"エネルギー(マーク)?(ミラー|柄)"),
        ("ボールミラー", r"ボール(ミラー|柄)"),
    ],
    [("未開封", r"未開封")],
    [("エラー", r"エラー")],
    [("色違い", r"色違い")],
    [("ジャンボ", r"ジャンボ")],
    [("英語版", r"英語版?"), ("中国語版", r"中国語版?"), ("韓国語版", r"韓国語版?")],
]
# 仕様の欄に書かれていても、カードを区別する情報ではないもの（レアリティの言い換えなど）
_NOISE = re.compile(r"(ノーマル|ハイクラスパック|[A-Za-z]{1,4})仕様|柄|ミラー|仕様|番号|[/:：・│|,、()（）\s]")


def variant_tags(variant: str) -> tuple[tuple[str, ...], str]:
    """仕様の書き方を (値段を左右する仕様の組, それ以外の言葉) に分ける。

    例: 「マスターボール柄/ミラー仕様」も「マスターボールミラー」も (("マスターボールミラー",), "") になる。
    それ以外の言葉は、同じ店に同じ仕様の行がいくつもあるときの見分けにだけ使う。
    """
    text = unicodedata.normalize("NFKC", variant)
    hard = []
    for group in _HARD_RULES:
        for label, pattern in group:
            if re.search(pattern, text, re.IGNORECASE):
                hard.append(label)
                text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
                break
    mirror = "ミラー" if "ミラー" in text and not any("ミラー" in h for h in hard) else ""
    soft = mirror + _NOISE.sub("", text).lower()
    return tuple(hard), soft


def assign_groups(loaded: dict[str, list[Price]]) -> dict[tuple[str, str], str]:
    """(店, 商品の識別子) ごとに「同じカード」を表すキーを返す。型番のない商品は入らない。

    1. 名前・型番・値段を左右する仕様（1ED、ミラーの種類、未開封など）が同じものを1つの山にする
    2. 山の中で、どの店も1行ずつしかなければ、同じカードとみなす（残りの言葉は店ごとの説明の違い）
    3. 同じ店に2行以上あるときは、残りの言葉まで一致したものだけを同じカードとみなす
    """
    piles: dict[tuple, dict[str, list[tuple[Price, str]]]] = defaultdict(lambda: defaultdict(list))
    for shop, prices in loaded.items():
        for p in prices:
            key = match_key(p)
            if key is None:
                continue
            hard, soft = variant_tags(p.variant)
            piles[(key, hard)][shop].append((p, soft))
    out: dict[tuple[str, str], str] = {}
    for (key, hard), shops in piles.items():
        base = "|".join(key).lower() + ("|" + "・".join(hard) if hard else "")
        clear = all(len(rows) == 1 for rows in shops.values())
        for shop, rows in shops.items():
            for p, soft in rows:
                out[(shop, p.item_id)] = base if clear or not soft else f"{base}|{soft}"
    return out


def group_label(variant: str) -> str:
    """画面に出す仕様の呼び名。値段を左右する仕様がなければ空文字。"""
    return "・".join(variant_tags(variant)[0])


def cross_shop(buyers: dict[str, list[Price]], sellers: dict[str, list[Price]], min_buy: int = 3000) -> list[dict]:
    """buyers の買取価格が sellers の販売価格を上回る組み合わせを、差額の大きい順に返す。

    仕様までそろった同じカードどうしだけを比べる。
    """
    groups = assign_groups({**sellers, **buyers})
    by_key: dict[str, list[tuple[str, Price]]] = defaultdict(list)
    for shop, prices in sellers.items():
        for p in prices:
            key = groups.get((shop, p.item_id))
            if key and p.sell_price:
                by_key[key].append((shop, p))
    rows = []
    for buy_shop, prices in buyers.items():
        for b in prices:
            key = groups.get((buy_shop, b.item_id))
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
