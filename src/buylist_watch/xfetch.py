"""X（Twitter）に店が出す買取表の投稿を、画像ごと手元に保存する。

twscrape を使う。X にログインしたアカウントが要るので、手元のPCかサーバーで動かす。
保存先（x_inbox/）とログイン情報（accounts.db）は .gitignore に入れてあり、このリポジトリには置かない。
店の画像そのものを公開の場所に置かないためでもある。

  x_inbox/<アカウント>/<投稿のID>/post.json   投稿の本文・日時・URL・画像の一覧
  x_inbox/<アカウント>/<投稿のID>/1.jpg ...   画像

ここでするのは「取ってきて保存する」までで、画像を読むこと（カード名や価格にすること）はしない。
X の規約は自動取得を認めていないので、アカウントが止められることがある。捨ててよいアカウントで、
1日1回・少ない件数にとどめる。
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .http import Fetcher

JST = timezone(timedelta(hours=9))


def load_accounts(path: Path) -> list[str]:
    """対象のアカウントを読む。1行に1つ。先頭の @ と、# から後ろは読み飛ばす。"""
    logins = []
    for line in path.read_text(encoding="utf-8").splitlines():
        login = line.split("#", 1)[0].strip().lstrip("@")
        if login and login not in logins:
            logins.append(login)
    return logins


def post_record(tweet) -> dict | None:
    """保存する形にする。画像のない投稿と、ほかの人の投稿の再投稿（リポスト）は対象外で None。"""
    photos = [p.url for p in (tweet.media.photos if tweet.media else [])]
    if not photos or tweet.retweetedTweet is not None:
        return None
    return {
        "id": tweet.id_str,
        "account": tweet.user.username,
        "url": tweet.url,
        "posted_at": tweet.date.astimezone(JST).isoformat(timespec="seconds"),
        "text": tweet.rawContent,
        "photos": photos,
    }


def save_post(record: dict, out_dir: Path, download) -> bool:
    """1つの投稿を保存する。すでに保存済みなら何もせず False を返す。

    post.json は画像をすべて保存したあとで書く。途中で止まった投稿は、次の回に取り直される。
    """
    post_dir = out_dir / record["account"] / record["id"]
    if (post_dir / "post.json").exists():
        return False
    post_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for n, url in enumerate(record["photos"], 1):
        ext = Path(urlparse(url).path).suffix or ".jpg"
        (post_dir / f"{n}{ext}").write_bytes(download(url))
        files.append(f"{n}{ext}")
    (post_dir / "post.json").write_text(json.dumps(dict(record, files=files), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


async def fetch_account(api, login: str, out_dir: Path, since: datetime, limit: int, download) -> tuple[int, int]:
    """1つのアカウントの新しい投稿を保存して、(保存した数, 保存済みで飛ばした数) を返す。"""
    user = await api.user_by_login(login)
    if user is None:
        raise ValueError(f"@{login} が見つかりません（名前の間違いか、アカウントが非公開・凍結）")
    saved = skipped = 0
    async for tweet in api.user_tweets(user.id, limit=limit):
        record = post_record(tweet)
        # 固定された古い投稿が先頭に来ることがあるので、古い投稿に当たっても打ち切らずに読み進める
        if record is None or tweet.date < since:
            continue
        if save_post(record, out_dir, download):
            saved += 1
        else:
            skipped += 1
    return saved, skipped


async def fetch_all(api, logins: list[str], out_dir: Path, days: int, limit: int, download, pause: float = 5.0) -> bool:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    ok = True
    for n, login in enumerate(logins):
        if n:
            await asyncio.sleep(pause)  # アカウントごとに間を空ける
        try:
            saved, skipped = await fetch_account(api, login, out_dir, since, limit, download)
            print(f"@{login}: {saved}件を保存（保存済み {skipped}件）", flush=True)
        except Exception as e:  # 1つの失敗で、ほかのアカウントを止めない
            ok = False
            if type(e).__name__ == "NoAccountError":
                # twscrape に、使えるログイン情報がない。ほかのアカウントを試しても同じなので、ここでやめる
                print("X にログインできるアカウントがありません。twscrape accounts で状態を確かめてください"
                      "（未登録、Cookie の期限切れ、アカウントの停止、短時間に使いすぎたときの一時停止）", file=sys.stderr, flush=True)
                break
            print(f"@{login}: 失敗しました: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return ok


def run(accounts_file: Path, db: Path, out_dir: Path, days: int, limit: int) -> int:
    try:
        from twscrape import API
    except ImportError:
        print("twscrape が入っていません。pip install twscrape を実行してください", file=sys.stderr)
        return 1
    if not accounts_file.exists():
        print(f"{accounts_file} がありません。対象のXアカウントを1行に1つ書いてください", file=sys.stderr)
        return 1
    logins = load_accounts(accounts_file)
    if not logins:
        print(f"{accounts_file} にアカウントが1つも書かれていません", file=sys.stderr)
        return 1
    if not db.exists():
        print(f"{db} がありません。先に twscrape --db {db} add_cookie … でログイン情報を登録してください（README を参照）", file=sys.stderr)
        return 1
    # ログインできるアカウントがないとき、待ち続けずにエラーで終わる
    api = API(str(db), raise_when_no_account=True)
    fetcher = Fetcher(delay=0.5)
    return 0 if asyncio.run(fetch_all(api, logins, out_dir, days, limit, fetcher.get)) else 1
