"""チェッカー（静的サイト）の生成。

web/ のページをコピーして、ページが読み込む data.json を data/ から作る。
GitHub Pages に置く前提で、サーバー側の処理は持たない。
"""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from . import compare, store
from .sources import SOURCES

MOVER_KINDS = {"up", "down", "new", "removed"}


def _int(value: str) -> int | None:
    return int(value) if value not in ("", None) else None


def read_changes(src_dir: Path) -> list[tuple[str, list[dict]]]:
    """(日付, 行の一覧) を古い順に返す。"""
    out = []
    for path in sorted((src_dir / "changes").glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as f:
            out.append((path.stem, list(csv.DictReader(f))))
    return out


def build_history(changes: list[tuple[str, list[dict]]], max_points: int = 90) -> dict[str, list]:
    """商品ごとの買取価格の推移。[日付, 価格] の並びで、最初の点の日付 "" は「記録を始める前」を表す。"""
    history: dict[str, list] = {}
    for date, rows in changes:
        for r in rows:
            if r["change"] not in MOVER_KINDS:
                continue
            old, new = _int(r["old_buy"]), _int(r["new_buy"])
            points = history.setdefault(r["item_id"], [])
            if not points and old is not None:
                points.append(["", old])
            points.append([date, new if new is not None else 0])
    return {k: v[-max_points:] for k, v in history.items()}


def build_movers(shop: int, changes: list[tuple[str, list[dict]]], days: int = 7, min_price: int = 3000) -> list[list]:
    """直近の値動き。[日付, 店, 種類, 名前, 仕様, セット, 型番, 前の買取, 今の買取]"""
    out = []
    for date, rows in changes[-days:]:
        for r in rows:
            if r["change"] not in MOVER_KINDS:
                continue
            old, new = _int(r["old_buy"]) or 0, _int(r["new_buy"]) or 0
            if max(old, new) < min_price:
                continue
            out.append([date, shop, r["change"], r["name"], r["variant"], r["set_code"], r["number"], old, new])
    return out


def build_data(data_dir: Path, min_buy: int = 1000, cross_limit: int = 300) -> dict:
    shops, items, movers, history = [], [], [], {}
    loaded = {}
    for name in SOURCES:
        loaded[name] = store.read_latest(data_dir / name / "latest.csv")
    # どこかの店が min_buy 以上で買い取っているカード。ほかの店は買取が安くても比べるために載せる
    wanted = {compare.match_key(p) for prices in loaded.values() for p in prices if p.buy_price >= min_buy}
    wanted.discard(None)
    for shop, name in enumerate(SOURCES):
        src_dir = data_dir / name
        prices = loaded[name]
        meta_path = src_dir / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        shops.append({"id": name, "fetched_at": meta.get("fetched_at", ""), "count": len(prices)})
        if not prices:
            continue
        kept = set()
        for p in prices:
            if p.buy_price >= min_buy or compare.match_key(p) in wanted:
                kept.add(p.item_id)
                items.append([shop, p.item_id, p.name, p.variant, p.set_code, p.number, p.rarity, p.buy_price, p.sell_price or 0])
        changes = read_changes(src_dir)
        movers += build_movers(shop, changes)
        for item_id, points in build_history(changes).items():
            if item_id in kept:
                history[f"{shop}:{item_id}"] = points
    movers.sort(key=lambda m: (m[0], abs(m[8] - m[7])), reverse=True)
    loaded = {k: v for k, v in loaded.items() if v}
    cross = compare.cross_shop(loaded, loaded)[:cross_limit] if len(loaded) >= 2 else []
    return {
        "generated_at": max((s["fetched_at"] for s in shops), default=""),
        "min_buy": min_buy,
        "shops": shops,
        "items": items,
        "movers": movers,
        "history": history,
        "cross": [[r[k] for k in compare.REPORT_FIELDS] for r in cross],
    }


def build(data_dir: Path, web_dir: Path, out_dir: Path, min_buy: int = 1000) -> dict:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(web_dir, out_dir)
    data = build_data(data_dir, min_buy=min_buy)
    (out_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return data
