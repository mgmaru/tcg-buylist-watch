"""取得元の店。

店を足すときは、モジュールを作ってここの SOURCES の最後に登録する。
画面は店を番号（この並び順）で覚えているので、途中に入れたり並べ替えたりしない
（価格の履歴の持ち主やグラフの色がずれる）。

モジュールが持つもの:
  NAME   保存先のフォルダ名にもなる、英数字の識別子
  LABEL  画面に出す店の名前
  LINK   カードの詳細から店のページを開くリンク (文言, URL)。なければ None。
         URL の {name} はカード名、{word} は検索語（カード名と型番）に置き換わる
  fetch(fetcher, max_pages)  Price を1件ずつ返す
"""

from . import bigweb, cardrush, hareruya2, yuyutei

SOURCES = {cardrush.NAME: cardrush, hareruya2.NAME: hareruya2, yuyutei.NAME: yuyutei, bigweb.NAME: bigweb}


def describe(name: str) -> dict:
    """画面に渡す店の情報。"""
    module = SOURCES[name]
    link = getattr(module, "LINK", None)
    return {"label": getattr(module, "LABEL", name), "link": {"text": link[0], "url": link[1]} if link else None}
