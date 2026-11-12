"""取得結果の保存。

data/<店>/latest.csv        最新の全件（毎回上書き）
data/<店>/changes/<日付>.csv 前回から変わった行だけ
data/<店>/meta.json         取得日時と件数

全件を日付ごとに残すとリポジトリがすぐ大きくなるので、履歴は差分だけにする。
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path

from .models import CSV_FIELDS, Price

CHANGE_FIELDS = ["change", "item_id", "name", "variant", "set_code", "number", "old_buy", "new_buy", "old_sell", "new_sell"]


def _sort_key(p: Price):
    return (0, int(p.item_id), "") if p.item_id.isdigit() else (1, 0, p.item_id)


def dedupe(prices: Iterable[Price]) -> list[Price]:
    """同じ item_id は最初の1件だけ残して、順番を固定する。"""
    seen: dict[str, Price] = {}
    for p in prices:
        seen.setdefault(p.item_id, p)
    return sorted(seen.values(), key=_sort_key)


def read_latest(path: Path) -> list[Price]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return [
            Price(
                item_id=r["item_id"],
                name=r["name"],
                variant=r["variant"],
                set_code=r["set_code"],
                number=r["number"],
                rarity=r["rarity"],
                buy_price=int(r["buy_price"] or 0),
                sell_price=int(r["sell_price"]) if r["sell_price"] else None,
                source_updated_at=r["source_updated_at"],
            )
            for r in csv.DictReader(f)
        ]


def write_latest(path: Path, prices: list[Price]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        for p in prices:
            row = asdict(p)
            row["sell_price"] = "" if p.sell_price is None else p.sell_price
            w.writerow(row)


def diff(old: list[Price], new: list[Price], removals: bool = True) -> list[dict]:
    """前回と今回を比べて、変わった行を返す。

    change は new（新規）/ removed（掲載終了）/ up / down（買取価格の上下）/ sell（販売価格だけ変化）。
    一部のページだけ取得したときは removals=False にして、掲載終了の誤判定を防ぐ。
    """
    before = {p.item_id: p for p in old}
    after = {p.item_id: p for p in new}
    out = []

    def row(change: str, p: Price, o: Price | None, n: Price | None) -> dict:
        return {
            "change": change,
            "item_id": p.item_id,
            "name": p.name,
            "variant": p.variant,
            "set_code": p.set_code,
            "number": p.number,
            "old_buy": "" if o is None else o.buy_price,
            "new_buy": "" if n is None else n.buy_price,
            "old_sell": "" if o is None or o.sell_price is None else o.sell_price,
            "new_sell": "" if n is None or n.sell_price is None else n.sell_price,
        }

    for item_id, n in after.items():
        o = before.get(item_id)
        if o is None:
            out.append(row("new", n, None, n))
        elif n.buy_price != o.buy_price:
            out.append(row("up" if n.buy_price > o.buy_price else "down", n, o, n))
        elif n.sell_price != o.sell_price:
            out.append(row("sell", n, o, n))
    if removals:
        for item_id, o in before.items():
            if item_id not in after:
                out.append(row("removed", o, o, None))
    return out


def merge_changes(earlier: list[dict], later: list[dict]) -> list[dict]:
    """同じ日に2回取得したときの変化をまとめる。その日の最初の値と最後の値を比べた形にする。"""
    merged = {r["item_id"]: dict(r) for r in earlier}
    for r in later:
        first = merged.get(r["item_id"])
        if first is None:
            merged[r["item_id"]] = dict(r)
            continue
        row = dict(r, old_buy=first["old_buy"], old_sell=first["old_sell"])
        if first["change"] == "new":
            # 朝に載って、その日のうちに消えたものは記録しない
            row["change"] = None if r["change"] == "removed" else "new"
        elif r["change"] != "removed":
            old, new = int(row["old_buy"] or 0), int(row["new_buy"] or 0)
            if new != old:
                row["change"] = "up" if new > old else "down"
            else:
                row["change"] = "sell" if str(row["old_sell"]) != str(row["new_sell"]) else None
        if row["change"] is None:
            del merged[r["item_id"]]
        else:
            merged[r["item_id"]] = row
    return list(merged.values())


SHRINK_LIMIT = 0.7  # 件数が前回のこの割合を下回ったら、取得の失敗か店側の作業中を疑う
SHRINK_ACCEPT_HOURS = 24  # 減った状態がこの時間続いたら、店が本当に掲載を減らしたとみなして保存する


class ShrinkError(ValueError):
    """件数が急に減ったので保存を見送った。少し待って取り直すと直ることが多い。"""


def _read_meta(src_dir: Path) -> dict:
    path = src_dir / "meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_meta(src_dir: Path, meta: dict) -> None:
    (src_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hold(src_dir: Path, source: str, old_count: int, new_count: int, fetched_at: str) -> bool:
    """保存の見送りを meta.json に記録する。減った状態が十分長く続いていたら True（保存してよい）を返す。"""
    meta = _read_meta(src_dir)
    held = meta.get("held") or {}
    # 前に見送ったときと件数が大きく違えば、別の出来事として数え直す
    same = held and abs(held["count"] - new_count) <= max(old_count * 0.05, 1)
    since = held["since"] if same else fetched_at
    hours = (datetime.fromisoformat(fetched_at) - datetime.fromisoformat(since)).total_seconds() / 3600
    if same and hours >= SHRINK_ACCEPT_HOURS:
        return True
    meta["held"] = {"since": since, "last": fetched_at, "count": new_count, "times": (held.get("times", 0) if same else 0) + 1}
    _write_meta(src_dir, meta)
    return False


def save(data_dir: Path, source: str, prices: Iterable[Price], fetched_at: str, partial: bool = False, force: bool = False) -> dict:
    """保存して、件数と変化の数を返す。partial は一部だけ取得した試し実行のとき True。

    件数が前回から大きく減ったときは保存せず、ShrinkError を出す（店が買取表を入れ替えている途中の
    状態を拾って、大量の「掲載終了」を誤って記録しないため）。見送ったことは meta.json の held に残す。
    減った状態が SHRINK_ACCEPT_HOURS 時間続いたら、店が本当に減らしたとみなして自動で保存する。
    すぐに保存したいときは force=True にする。
    """
    src_dir = data_dir / source
    latest = src_dir / "latest.csv"
    new = dedupe(prices)
    if not new:
        raise ValueError(f"{source}: 1件も取得できませんでした。前回のデータは残します")
    old = read_latest(latest)
    if old and not partial and not force and len(new) < len(old) * SHRINK_LIMIT:
        if not _hold(src_dir, source, len(old), len(new), fetched_at):
            raise ShrinkError(
                f"{source}: 件数が {len(old)}件 から {len(new)}件 に大きく減りました。前回のデータを残します"
                "（店が買取表を更新している途中かもしれません）"
            )
    changes = diff(old, new, removals=not partial) if old else []
    if partial and old:
        # 試し実行では、取得しなかった行を前回のまま残す
        merged = {p.item_id: p for p in old}
        merged.update({p.item_id: p for p in new})
        new = dedupe(merged.values())
    write_latest(latest, new)
    if changes:
        path = src_dir / "changes" / f"{fetched_at[:10]}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # 同じ日の2回目以降。朝の記録を消さずにまとめる
            with path.open(encoding="utf-8", newline="") as f:
                changes = merge_changes(list(csv.DictReader(f)), changes)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CHANGE_FIELDS, lineterminator="\n")
            w.writeheader()
            w.writerows(changes)
    # first_fetched_at は記録を始めた日時。価格の推移を「いつから見ているか」に使う
    first = _read_meta(src_dir).get("first_fetched_at") or fetched_at
    meta = {"source": source, "first_fetched_at": first, "fetched_at": fetched_at, "count": len(new), "changes": len(changes),
            "partial": partial}
    _write_meta(src_dir, meta)  # 保存できたので、見送りの記録（held）は消える
    return meta
