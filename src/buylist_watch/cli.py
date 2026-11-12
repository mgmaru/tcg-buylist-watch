from __future__ import annotations

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import compare, site, store
from .http import Fetcher
from .sources import SOURCES

JST = timezone(timedelta(hours=9))


def cmd_fetch(args) -> int:
    names = list(SOURCES) if args.source == "all" else [args.source]

    def one(name: str) -> bool:
        try:
            for attempt in range(args.shrink_retries + 1):
                fetched_at = datetime.now(JST).isoformat(timespec="seconds")
                # 店ごとに別の Fetcher を持つ。取得の間隔は店ごとに守られる
                prices = list(SOURCES[name].fetch(Fetcher(delay=args.delay), max_pages=args.max_pages))
                try:
                    meta = store.save(Path(args.data_dir), name, prices, fetched_at, partial=args.max_pages is not None, force=args.force)
                except store.ShrinkError as e:
                    # 店が買取表を入れ替えている途中のことが多い。少し待って取り直す
                    if attempt == args.shrink_retries:
                        raise
                    print(f"{e}。{args.shrink_wait}秒待って取り直します（{attempt + 1}回目）", file=sys.stderr, flush=True)
                    time.sleep(args.shrink_wait)
                    continue
                print(f"{name}: {meta['count']}件を保存、前回からの変化 {meta['changes']}件", flush=True)
                return True
        except Exception as e:  # 1店の失敗でほかの店を止めない
            print(f"{name}: 失敗しました: {e}", file=sys.stderr, flush=True)
        return False

    # 店は別々のサイトなので同時に取りに行く。保存先も店ごとに分かれているのでぶつからない
    with ThreadPoolExecutor(max_workers=max(1, min(args.jobs, len(names)))) as pool:
        results = list(pool.map(one, names))
    return 0 if all(results) else 1


def cmd_compare(args) -> int:
    data_dir = Path(args.data_dir)
    loaded = {name: store.read_latest(data_dir / name / "latest.csv") for name in SOURCES}
    loaded = {k: v for k, v in loaded.items() if v}
    if len(loaded) < 2:
        print("比べるには2店以上のデータが必要です。先に fetch を実行してください", file=sys.stderr)
        return 1
    rows = compare.cross_shop(loaded, loaded, min_buy=args.min_buy)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=compare.REPORT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}件の候補を {out} に書きました。差額の大きい順に{min(args.top, len(rows))}件:")
    for r in rows[: args.top]:
        print(
            f"  {r['name']} {r['number']}  {r['buy_shop']}買取 {r['buy_price']:,}円"
            f" > {r['sell_shop']}販売 {r['sell_price']:,}円（{r['sell_variant'] or '仕様の記載なし'}）"
            f"  差額 {r['gap']:,}円"
        )
    return 0


def cmd_site(args) -> int:
    data = site.build(Path(args.data_dir), Path(args.web_dir), Path(args.out))
    print(f"{args.out} にサイトを作りました。カード {len(data['items'])}件、値動き {len(data['movers'])}件、店の差 {len(data['cross'])}件")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="buylist-watch", description="カードショップの買取表を取得して比べる")
    parser.add_argument("--data-dir", default="data")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fetch", help="買取表を取得して保存する")
    f.add_argument("--source", default="all", choices=["all", *SOURCES])
    f.add_argument("--max-pages", type=int, default=None, help="試し実行用。ページ数を制限する")
    f.add_argument("--delay", type=float, default=1.5, help="1回の取得ごとに空ける秒数（店ごと）")
    f.add_argument("--force", action="store_true", help="件数が前回から大きく減っていても保存する")
    f.add_argument("--shrink-retries", type=int, default=2, help="件数が急に減ったとき、待って取り直す回数")
    f.add_argument("--shrink-wait", type=float, default=600, help="取り直すまで待つ秒数")
    f.add_argument("--jobs", type=int, default=len(SOURCES), help="同時に取得する店の数。1にすると順番に取得する")
    f.set_defaults(func=cmd_fetch)

    c = sub.add_parser("compare", help="ある店の買取価格が別の店の販売価格より高いカードを探す")
    c.add_argument("--min-buy", type=int, default=3000)
    c.add_argument("--top", type=int, default=20)
    c.add_argument("--out", default="reports/cross_shop.csv")
    c.set_defaults(func=cmd_compare)

    s = sub.add_parser("site", help="チェッカーの静的サイトを作る")
    s.add_argument("--web-dir", default="web")
    s.add_argument("--out", default="_site")
    s.set_defaults(func=cmd_site)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
