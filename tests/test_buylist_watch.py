import csv
import json
import tempfile
import unittest
from pathlib import Path

from buylist_watch import compare, site, store
from buylist_watch.models import Price
from buylist_watch.sources import SOURCES, bigweb, cardrush, clabo, dorasuta, hareruya2, yuyutei


def price(item_id="1", name="ゴンベ", number="069/090", buy=60000, sell=None, variant="", set_code="DPt2-B"):
    return Price(item_id=item_id, name=name, variant=variant, set_code=set_code, number=number, rarity="●",
                 buy_price=buy, sell_price=sell)


class CardrushTest(unittest.TestCase):
    def html(self, rows, last_page=3):
        data = {"props": {"pageProps": {"buyingPrices": rows, "lastPage": last_page}}}
        return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script></html>'

    def test_parse_page(self):
        rows = [{"id": 99, "pokemon_ocha_product_id": 18773, "name": "ゴンベ", "extra_difference": "未開封", "rarity": "P",
                 "model_number": "125/DP-P", "pack_code": "その他", "amount": 120000, "updated_at": "2026-11-11T10:00:42+09:00"}]
        prices, last = cardrush.parse_page(self.html(rows))
        self.assertEqual(last, 3)
        self.assertEqual(prices[0].item_id, "18773")
        self.assertEqual(prices[0].variant, "未開封")
        self.assertEqual(prices[0].buy_price, 120000)
        self.assertIsNone(prices[0].sell_price)

    def test_missing_product_id_falls_back_to_name_and_number(self):
        rows = [{"name": "ゴンベ", "extra_difference": None, "model_number": "069/090", "amount": 60000}]
        prices, _ = cardrush.parse_page(self.html(rows))
        self.assertEqual(prices[0].item_id, "ゴンベ|069/090|")

    def test_changed_page_structure_is_an_error(self):
        with self.assertRaises(ValueError):
            cardrush.parse_page("<html></html>")


class Hareruya2Test(unittest.TestCase):
    def test_parse_title_with_variant(self):
        self.assertEqual(hareruya2.parse_title("ポニータ:色違い:1ED(C){炎}〈019/090〉[Pt4]"),
                         ("ポニータ", "色違い:1ED", "C", "019/090", "Pt4"))

    def test_parse_title_plain(self):
        self.assertEqual(hareruya2.parse_title("ゴンベ(C){無}〈069/090〉[Pt2]"), ("ゴンベ", "", "C", "069/090", "Pt2"))

    def test_parse_title_unknown_shape_keeps_name(self):
        self.assertEqual(hareruya2.parse_title("【未開封プロモ】ゴンベ 125/DP-P")[0], "【未開封プロモ】ゴンベ 125/DP-P")

    def test_parse_json(self):
        raw = json.dumps({"date": "2026/11/11 09:41", "products": [
            {"id": 7, "title": "ゴンベ(C){無}〈069/090〉[Pt2]", "sell_price": 30000, "buy_price": 0},
            {"id": 8, "title": "おすすめルール(?){}〈-〉[OPE]", "sell_price": 5000, "buy_price": 2000},
        ]}).encode()
        prices = hareruya2.parse(raw)
        self.assertEqual((prices[0].sell_price, prices[0].buy_price), (30000, 0))
        self.assertEqual(prices[1].number, "")


def bigweb_item(item_id, name, fname, comment, rarity, slip, price):
    return {"id": item_id, "name": name, "fname": fname, "comment": comment, "rarity": {"web": rarity},
            "cardset": {"slip": slip}, "price": price, "stock_count": 3, "is_sold_out": False}


class BigwebTest(unittest.TestCase):
    def one(self, *args):
        return bigweb.parse_item(bigweb_item(*args))

    def test_parse_plain_card(self):
        p = self.one(3582558, "ピカチュウex", "【M6a】【J】", "(127/103) なんば店で展示中(3枚)", "SAR", "【M6a】30th CELEBRATION", 3600)
        self.assertEqual((p.item_id, p.name, p.variant, p.set_code, p.number, p.rarity, p.buy_price, p.sell_price),
                         ("3582558", "ピカチュウex", "", "M6a", "127/103", "SAR", 3600, None))

    def test_spec_words_move_from_the_name_to_the_variant(self):
        # 同じ仕様が名前・商品名・レアリティの3か所に書いてあっても、1つにまとめる
        p = self.one(1, "クルミル(マスターボール柄)", "【SV11W】【I】(マスターボール柄ミラー)", "(001/086)", " - (ミラー)", "【SV11W】ホワイトフレア", 150)
        self.assertEqual((p.name, p.variant, p.rarity), ("クルミル", "マスターボール柄ミラー", ""))
        p = self.one(2, "カイリュー【Lv.45】", "【旧裏面 第3弾】", "<strong>※買取特記事項</strong>…", "★(キラ）", "【旧裏3】", 20000)
        self.assertEqual((p.name, p.variant, p.set_code, p.number, p.rarity), ("カイリュー", "Lv.45 キラ", "旧裏3", "", "★"))
        self.assertEqual(self.one(3, "(未開封)名探偵ピカチュウ", "【SM-P】", "(337/SM-P)", "プロモ", "【SM-P】", 9000).variant, "未開封")

    def test_person_and_form_names_stay_in_the_name(self):
        # ほかの店は人名や姿を名前に含めているので、合わせる
        self.assertEqual(self.one(1, "ボスの指令(ゲーチス)", "【SV1a】【G】", "(095/073)", "SR", "【SV1a】トリプレットビート", 2000).name,
                         "ボスの指令(ゲーチス)")
        p = self.one(2, "ルギア(クリスタルタイプ)(30th復刻版)", "【M6a】【J】", "(142/103)", " - (キラ無表記)", "【M6a】30th CELEBRATION", 15000)
        self.assertEqual((p.name, p.variant), ("ルギア(クリスタルタイプ)", "30th復刻版 キラ無表記"))

    def test_first_edition_and_state_are_recorded_as_variant(self):
        p = self.one(1, "ミツル", "【1ED】【CP3】", "(032/032)【状態A】", "SR", "【CP3】ポケキュンコレクション", 1300)
        self.assertEqual((p.variant, p.set_code, p.number), ("1ED 状態A", "CP3", "032/032"))
        self.assertEqual(self.one(2, "コルニ", "【1ED】【ポケモンカードゲームXY】", "(102/096)", "SR", "【XY3】", 76000).set_code, "XY3")

    def test_set_code_uses_the_finer_one_when_the_category_groups_packs(self):
        self.assertEqual(self.one(1, "ガラルヤドラン", "【sI】", "(252/414)", "TD", "【sI/sN】", 5).set_code, "sI")
        self.assertEqual(self.one(2, "リーリエ", "【s8a-P】", "(020/025)", "プロモ", "【s8a】25th ANNIVERSARY COLLECTION", 9000).set_code, "s8a")
        self.assertEqual(self.one(3, "旧裏面キラカード一律買取", "1枚500円", "1枚500円", "-", "買取専用", 500).set_code, "")

    def test_fetch_follows_the_page_count(self):
        def page(n):
            return json.dumps({"success": True, "items": [bigweb_item(n, f"カード{n}", "【M6】", "(001/076)", "C", "【M6】", 10)],
                               "pagenate": {"count": 3, "pageCount": 3, "page": n}}).encode()

        class Fake:
            urls = []

            def get(self, url):
                self.urls.append(url)
                return page(int(url.rsplit("=", 1)[1]))

        fake = Fake()
        self.assertEqual([p.item_id for p in bigweb.fetch(fake)], ["1", "2", "3"])
        self.assertTrue(all("is_purchase=1" in u for u in fake.urls))
        self.assertEqual(len(list(bigweb.fetch(Fake(), max_pages=2))), 2)

    def test_changed_json_shape_is_an_error(self):
        with self.assertRaises(ValueError):
            bigweb.parse(b'{"success": false}')


DORA_ITEM = """<div class="element"><div class="content"><a href="/pokemon-card/product?pid={pid}">
<img class="lazyload" alt="{name}"/></a>{sold}</div><div class="description"><ul>
<li class="change_hight">
  <a href="/pokemon-card/product?pid={pid}">
    {name}
  </a>
  <p>
    {rarity}
  </p>
  <p>
    PN000000
  </p>
</li>
<li>{price}円</li>
</ul></div></div>
<div class="list"><a href="/pokemon-card/product?pid={pid}">{name}</a><p>{rarity}</p><div>{price}円</div></div>"""


def dora_page(items, now=1, last=1):
    body = "".join(DORA_ITEM.format(pid=pid, name=name, rarity=rarity, price=f"{price:,}",
                                    sold='<a class="condition soldout"><span>SOLDOUT</span></a>' if sold else "")
                   for pid, name, rarity, price, sold in items)
    return (f'<input type="hidden" id="page_now" name="page_now" value="{now}" />'
            f'<input type="hidden" id="page_max" name="page_max" value="{last}" />'
            f'<div class="pager"><div class="page_num_cur">{now}</div></div>' + body)


class DorasutaTest(unittest.TestCase):
    def test_parse_name(self):
        cases = {
            ("ミュウツーex(134/103)", "FUR"): ("ミュウツーex", "", "", "134/103", "FUR"),
            ("ルギアV(109/098 SR)", "SR"): ("ルギアV", "", "", "109/098", "SR"),
            ("ジラーチ(089/SM-P)", "プロモ"): ("ジラーチ", "", "", "089/SM-P", "プロモ"),
            # レアリティの欄の「ミラー」「ホイル」は仕様。名前に同じ言葉があれば1つにまとめる
            ("モンジャラ(114/165)(ミラー/マスターボール)", "ミラー"): ("モンジャラ", "ミラー/マスターボール", "", "114/165", ""),
            ("ジラーチ(ミラー/白枠)(090/173)", "ミラー"): ("ジラーチ", "ミラー/白枠", "", "090/173", ""),
            ("カメックス&ポッチャマGX(070/064 SR)[SA]", "SR"): ("カメックス&ポッチャマGX", "SA", "", "070/064", "SR"),
            ("ラフレシアGX[SA](062/049)", "SR"): ("ラフレシアGX", "SA", "", "062/049", "SR"),
            ("リザードンVMAX(C/キラ)(002/021)【SC】", "ホイル"): ("リザードンVMAX", "ホイル キラ SC", "", "002/021", "C"),
            # 人名は名前の一部として残す
            ("ボスの指令(サカキ)(112/096 HR)", "HR"): ("ボスの指令(サカキ)", "", "", "112/096", "HR"),
            ("ボスの指令(カラスバ)(SR仕様)(760/742)", "ホイル"): ("ボスの指令(カラスバ)", "ホイル SR仕様", "", "760/742", ""),
            # 型番がない商品は、名前を分けない
            ("【BW8】リーフィア(エナジークラッシュ/リーフブレード)", "未登録"): ("リーフィア(エナジークラッシュ/リーフブレード)", "", "BW8", "", ""),
            ("ジムバッジ(サカキ)(ホロ)(XY-P)(黄枠)", "プロモ"): ("ジムバッジ(サカキ)", "ホロ 黄枠", "", "XY-P", "プロモ"),
        }
        for (raw, rarity), want in cases.items():
            self.assertEqual(dorasuta.parse_name(raw, rarity), want, raw)

    def test_parse_page_reads_each_product_once(self):
        # 1つの商品が、画像つきの並びと一覧の並びの2回出てくる。SOLDOUT の印があっても買取価格は記録する
        page = dora_page([("711193", "ミュウツーex(134/103)", "FUR", 2500, False),
                          ("275925", "ジラーチ(089/SM-P)", "プロモ", 20000, True)], now=2, last=148)
        prices, now, last = dorasuta.parse_page(page)
        self.assertEqual((now, last), (2, 148))
        self.assertEqual([(p.item_id, p.name, p.number, p.rarity, p.buy_price, p.sell_price) for p in prices],
                         [("711193", "ミュウツーex", "134/103", "FUR", 2500, None), ("275925", "ジラーチ", "089/SM-P", "プロモ", 20000, None)])

    def test_fetch_walks_pages_and_stops_when_paging_breaks(self):
        class Fake:
            def __init__(self, stuck=False):
                self.stuck, self.urls = stuck, []

            def get(self, url):
                self.urls.append(url)
                n = 1 if self.stuck else len(self.urls)
                return dora_page([(str(n), f"カード{n}(00{n}/100)", "C", 10, False)], now=n, last=3).encode()

        fake = Fake()
        self.assertEqual([p.item_id for p in dorasuta.fetch(fake)], ["1", "2", "3"])
        self.assertIn("form400200_params%5B1%5D=2", fake.urls[1])
        self.assertEqual(len(list(dorasuta.fetch(Fake(), max_pages=1))), 1)
        with self.assertRaises(ValueError):  # 2ページ目を頼んでも1ページ目が返る
            list(dorasuta.fetch(Fake(stuck=True)))

    def test_changed_page_structure_is_an_error(self):
        with self.assertRaises(ValueError):
            dorasuta.parse_page("<html>メンテナンス中</html>")
        with self.assertRaises(ValueError):
            list(dorasuta.fetch(type("Empty", (), {"get": lambda self, url: dora_page([]).encode()})()))


CLABO_CELL = """<li class="list_item_cell wrapped_item flex_layout list_item_{pid}"><div class="item_data">
<a href="https://www.c-labo-kaitori.jp/product/{pid}" class="item_data_link"><div class="list_item_data"><p class="item_name">
<span class="goods_name">{title}</span>
</p><div class="item_info"><div class="price"><p class="selling_price">
<span class="figure">{price}<span class="currency_label after_price">円</span></span></p></div>
<p class="stock">募集数8枚</p></div></div></a></div></li>"""


def clabo_page(series, items, total, last=1):
    pager = "".join(f'<a href="/product-list/{series}?num=120&amp;sort=price-desc&amp;page={n}" class="pager_btn">{n}</a>'
                    for n in range(2, last + 1))
    cells = "".join(CLABO_CELL.format(pid=pid, title=title, price=f"{price:,}") for pid, title, price in items)
    return f'<div class="count"><span class="number">{total:,}</span><span class="count_suffix">件</span></div>{pager}<ul>{cells}</ul>'


class ClaboTest(unittest.TestCase):
    def test_parse_title(self):
        cases = {
            "【ポケカ】メガレックウザex【MUR】M6 113/076": ("メガレックウザex", "", "M6", "113/076", "MUR"),
            "【ポケカ】メガリザードンYex(MUR仕様)【-】MC 766/742": ("メガリザードンYex", "MUR仕様", "MC", "766/742", ""),
            "《未開封》【ポケカ】ピカチュウex(FUR仕様)【-】PROMO 131/M-P": ("ピカチュウex", "未開封 FUR仕様", "PROMO", "131/M-P", ""),
            "【ポケカ】グレイシア【ミラー/マスターボール柄】SV8A 040/187": ("グレイシア", "ミラー/マスターボール柄", "SV8A", "040/187", ""),
            "【ポケカ】ブラッキー(YU NAGABA)【ミラー】PROMO 067/SV-P": ("ブラッキー", "ミラー YU NAGABA", "PROMO", "067/SV-P", ""),
            "【ポケカ】ミュウ【RGB】M6a R/RGB (背景:赤)": ("ミュウ", "背景:赤", "M6a", "R/RGB", "RGB"),
            "【ポケカ】ピカチュウ(01/30)【-】M6a 017/103": ("ピカチュウ", "01/30", "M6a", "017/103", ""),
            # 人名や姿は名前の一部として残す。人名と仕様が1つのかっこに入っていれば、仕様だけ外す
            "【ポケカ】ボスの指令(ゲーチス)【SR】SV1A 095/073": ("ボスの指令(ゲーチス)", "", "SV1A", "095/073", "SR"),
            "【ポケカ】ボスの指令(カラスバ/SR仕様)【-】MC 760/742": ("ボスの指令(カラスバ)", "SR仕様", "MC", "760/742", ""),
            "【ポケカ】ゲンガー(グレート)【-】M6a 150/103": ("ゲンガー(グレート)", "", "M6a", "150/103", ""),
            # 形が違うもの（まとめ買取の案内など）は、名前だけ
            "【ポケカ】ポケモンカード　まとめ買取(郵送限定)": ("ポケモンカード　まとめ買取(郵送限定)", "", "", "", ""),
        }
        for raw, want in cases.items():
            self.assertEqual(clabo.parse_title(raw), want, raw)

    def test_parse_page(self):
        # キーワード検索の結果では、商品名の一部がタグで囲まれる
        page = clabo_page(927, [("99207", "【ポケカ】メガレックウザex【MUR】M6 113/076", 50000),
                                ("105148", ' <span class="result_emphasis"><b>【ポケカ】</b></span>ルナトーン【R】M1L 026/063', 20)],
                          total=367, last=4)
        prices, total, last = clabo.parse_page(page)
        self.assertEqual((total, last), (367, 4))
        self.assertEqual([(p.item_id, p.name, p.set_code, p.number, p.rarity, p.buy_price) for p in prices],
                         [("99207", "メガレックウザex", "M6", "113/076", "MUR", 50000), ("105148", "ルナトーン", "M1L", "026/063", "R", 20)])

    def fake(self, pages):
        class Fake:
            urls = []

            def get(self, url):
                self.urls.append(url)
                series, page = int(url.split("/product-list/")[1].split("?")[0]), int(url.rsplit("=", 1)[1])
                return pages.get((series, page), clabo_page(series, [], 0)).encode()

        return Fake()

    def test_fetch_walks_every_series_by_price(self):
        first = next(iter(clabo.SERIES))
        fake = self.fake({(first, 1): clabo_page(first, [("1", "【ポケカ】A【SR】M6 001/076", 900)], total=2, last=2),
                          (first, 2): clabo_page(first, [("2", "【ポケカ】B【SR】M6 002/076", 800)], total=2, last=2),
                          (645, 1): clabo_page(645, [("3", "【ポケカ】C【AR】SV10 099/098", 100)], total=1)})
        self.assertEqual([p.item_id for p in clabo.fetch(fake)], ["1", "2", "3"])
        self.assertEqual(len(fake.urls), len(clabo.SERIES) + 1)
        self.assertTrue(all("sort=price-desc" in u for u in fake.urls))
        self.assertEqual([p.item_id for p in clabo.fetch(self.fake({(first, 1): clabo_page(first, [("1", "【ポケカ】A【SR】M6 001/076", 900)],
                                                                                         total=2, last=2)}), max_pages=1)], ["1"])

    def test_fetch_stops_when_items_are_missing(self):
        # 一覧には2件とあるのに、読めたのが1件（並び順がずれて同じ商品が2回出た）
        first = next(iter(clabo.SERIES))
        cell = [("1", "【ポケカ】A【SR】M6 001/076", 900)]
        fake = self.fake({(first, 1): clabo_page(first, cell, total=2, last=2), (first, 2): clabo_page(first, cell, total=2, last=2)})
        with self.assertRaises(ValueError):
            list(clabo.fetch(fake))

    def test_changed_page_structure_is_an_error(self):
        with self.assertRaises(ValueError):
            clabo.parse_page("<html>メンテナンス中</html>")


YUYU_CARD = """<div class="card-product position-relative mt-4 {cls}"><a
href="https://yuyu-tei.jp/{kind}/poc/card/{ver}/{cid}"><div class="position-relative product-img">
<img src="x.jpg" alt="{number} {rarity} {name}" class="card img-fluid"/></div></a>
<span class="d-block border border-dark p-1 w-100 text-center my-2">{number}</span>
<a href="https://yuyu-tei.jp/{kind}/poc/card/{ver}/{cid}"><h4 class="text-primary fw-bold">{name}</h4></a>
<strong class="d-block text-end">
{price} 円
</strong></div>"""


def yuyu_page(kind, cards, last=1):
    head = '<input type="checkbox" class="versPhone" name="vers[]" value="xy04" id="a">\n<label for="a">[XY4] 拡張パック</label>'
    pager = "".join(f'<a href="?search_word=&page={n}">{n}</a>' for n in range(1, last + 1))
    body = "".join(YUYU_CARD.format(kind=kind, cls="sold-out" if p.endswith("x") else "", ver=v, cid=c, number=n, rarity=r, name=nm,
                                    price=p.rstrip("x")) for v, c, n, r, nm, p in cards)
    return (head + body + pager).encode("utf-8")


class YuyuteiTest(unittest.TestCase):
    def test_split_name(self):
        self.assertEqual(yuyutei.split_name("トゲデマル(番号無し)"), ("トゲデマル", "番号無し"))
        self.assertEqual(yuyutei.split_name("MゲンガーEX"), ("MゲンガーEX", ""))

    def test_parse_page(self):
        rows, last, labels = yuyutei.parse_page(yuyu_page("buy", [("xy04", "10097", "097/088", "UR", "MゲンガーEX", "88,000")], last=3).decode())
        self.assertEqual(rows, [{"ver": "xy04", "cid": "10097", "number": "097/088", "name": "MゲンガーEX", "rarity": "UR", "price": 88000, "in_stock": True}])
        self.assertEqual((last, labels), (3, {"xy04": "XY4"}))

    def test_fetch_joins_buy_and_sell(self):
        pages = {
            yuyutei.BUY_URL.format(page=1): yuyu_page("buy", [("xy04", "10097", "097/088", "UR", "MゲンガーEX", "88,000")]),
            yuyutei.SELL_URL.format(page=1): yuyu_page("sell", [
                ("xy04", "10097", "097/088", "UR", "MゲンガーEX", "128,000"),
                ("smp", "10011", "011/SM-P", "PROMO", "トゲデマル(番号無し)", "2,480"),
                ("smp", "10012", "012/SM-P", "PROMO", "バクガメス", "998,000x"),  # 末尾の x は在庫切れの印
            ]),
        }

        class Fake:
            def get(self, url):
                return pages[url]

        got = list(yuyutei.fetch(Fake()))
        self.assertEqual([(p.item_id, p.name, p.variant, p.set_code, p.rarity, p.buy_price, p.sell_price) for p in got], [
            ("xy04/10097", "MゲンガーEX", "", "XY4", "UR", 88000, 128000),
            ("smp/10011", "トゲデマル", "番号無し", "smp", "PROMO", 0, 2480),  # 販売だけの商品は買取0円で載せる
            ("smp/10012", "バクガメス", "", "smp", "PROMO", 0, None),  # 在庫切れの販売価格は記録しない
        ])


class StoreTest(unittest.TestCase):
    def test_diff_kinds(self):
        old = [price("1", buy=100), price("2", buy=100), price("3", buy=100), price("4", buy=100, sell=200)]
        new = [price("1", buy=150), price("2", buy=50), price("4", buy=100, sell=300), price("5", buy=10)]
        kinds = {c["item_id"]: c["change"] for c in store.diff(old, new)}
        self.assertEqual(kinds, {"1": "up", "2": "down", "4": "sell", "5": "new", "3": "removed"})

    def test_save_roundtrip_and_changes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            meta = store.save(data, "cardrush", [price("2"), price("10"), price("2", buy=1)], "2026-11-11T05:00:00+09:00")
            self.assertEqual((meta["count"], meta["changes"]), (2, 0))
            self.assertEqual([p.item_id for p in store.read_latest(data / "cardrush" / "latest.csv")], ["2", "10"])
            meta = store.save(data, "cardrush", [price("2", buy=70000), price("10")], "2026-11-12T05:00:00+09:00")
            self.assertEqual(meta["changes"], 1)
            self.assertTrue((data / "cardrush" / "changes" / "2026-11-12.csv").exists())

    def test_partial_run_keeps_unfetched_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            store.save(data, "cardrush", [price("1"), price("2")], "2026-11-11T05:00:00+09:00")
            meta = store.save(data, "cardrush", [price("1", buy=1)], "2026-11-12T05:00:00+09:00", partial=True)
            self.assertEqual((meta["count"], meta["changes"]), (2, 1))

    def test_empty_result_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                store.save(Path(tmp), "cardrush", [], "2026-11-11T05:00:00+09:00")


class CompareTest(unittest.TestCase):
    def test_finds_buy_above_other_shops_sell(self):
        rush = [price("1", name="コダック", number="026/096", buy=45000)]
        hare = [price("9", name="コダック", number="026/096", buy=0, sell=8000, set_code="Pt1"),
                price("8", name="コダック", number="025/096", buy=0, sell=100)]
        rows = compare.cross_shop({"cardrush": rush, "hareruya2": hare}, {"cardrush": rush, "hareruya2": hare})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["gap"], rows[0]["ratio"]), (37000, 5.62))

    def test_ignores_same_shop_small_buy_and_missing_number(self):
        a = [price("1", buy=45000, sell=100), price("2", name="ルール", number="", buy=45000)]
        b = [price("3", name="ルール", number="", sell=10), price("4", buy=2000, sell=1)]
        self.assertEqual(compare.cross_shop({"a": a}, {"a": a, "b": b}), [
            {"name": "ゴンベ", "number": "069/090", "buy_shop": "a", "buy_set": "DPt2-B", "buy_variant": "", "buy_price": 45000,
             "sell_shop": "b", "sell_set": "DPt2-B", "sell_variant": "", "sell_price": 1, "gap": 44999, "ratio": 45000.0}])

    def test_fullwidth_and_spaces_match(self):
        self.assertEqual(compare.norm("ＭミュウツーＥＸ "), "MミュウツーEX")

    def test_names_match_across_shop_punctuation(self):
        # 人名の付け方や中黒は店ごとに違う。型番が同じなら、同じカードとして扱う
        names = ["ボスの指令/サカキ", "ボスの指令[サカキ]", "ボスの指令（サカキ）", "ボスの指令 サカキ"]
        self.assertEqual({compare.name_key(n) for n in names}, {"ボスの指令サカキ"})
        self.assertEqual(compare.name_key("カプ・コケコGX"), compare.name_key("カプコケコGX"))
        loaded = {f"shop{i}": [price(str(i), name=n, number="092/096")] for i, n in enumerate(names)}
        self.assertEqual(len(set(compare.assign_groups(loaded).values())), 1)
        other = {"a": [price("1", name="ボスの指令/サカキ", number="092/096")], "b": [price("2", name="ボスの指令[ゲーチス]", number="092/096")]}
        self.assertEqual(len(set(compare.assign_groups(other).values())), 2)


class VariantTest(unittest.TestCase):
    def test_variant_tags_unify_shop_wording(self):
        self.assertEqual(compare.variant_tags("マスターボール柄/ミラー仕様"), (("マスターボールミラー",), ""))
        self.assertEqual(compare.variant_tags("マスターボールミラー"), (("マスターボールミラー",), ""))
        self.assertEqual(compare.variant_tags("再販")[0], compare.variant_tags("アンリミ")[0])
        self.assertEqual(compare.variant_tags("キラ1ED"), (("1ED",), "キラ"))
        self.assertEqual(compare.variant_tags("未開封/乱戦！ポケモンスクランブル")[0], ("未開封",))
        self.assertEqual(compare.variant_tags("RR仕様"), ((), ""))  # レアリティの言い換えは区別に使わない
        self.assertEqual(compare.variant_tags("ミラー仕様"), compare.variant_tags("ミラー"))
        # 新しく足した店の書き方
        self.assertEqual(compare.variant_tags("ミラー/マスターボール")[0], ("マスターボールミラー",))  # ドラゴンスター
        self.assertEqual(compare.variant_tags("モンスターボール柄ミラー")[0], ("モンスターボールミラー",))  # BIG-WEB
        self.assertEqual(compare.variant_tags("ミラー エネルギーマーク柄")[0], ("エネルギーミラー",))

    def test_corrected_version_is_not_the_error_version(self):
        self.assertEqual(compare.variant_tags("エラー版")[0], ("エラー",))
        self.assertEqual(compare.variant_tags("エラ―版")[0], ("エラー",))  # 横棒が別の文字
        self.assertEqual(compare.variant_tags("エラー修正版")[0], ("修正版",))
        self.assertEqual(compare.variant_tags("修正版")[0], ("修正版",))
        g = self.groups(a=["エラー版"], b=["エラー修正版"], c=["修正版"])
        self.assertEqual(g[("b", "エラー修正版")], g[("c", "修正版")])
        self.assertNotEqual(g[("a", "エラー版")], g[("b", "エラー修正版")])

    def groups(self, **shops):
        loaded = {shop: [price(f"{shop}{n}", name="ゲンガー", number="094/165", variant=v) for n, v in enumerate(variants)]
                  for shop, variants in shops.items()}
        got = compare.assign_groups(loaded)
        return {(shop, p.variant): got[(shop, p.item_id)] for shop, prices in loaded.items() for p in prices}

    def test_different_price_relevant_variants_are_never_the_same_card(self):
        g = self.groups(a=["マスターボールミラー", "1ED"], b=["", "マスターボール柄/ミラー仕様", "再販"])
        self.assertEqual(g[("a", "マスターボールミラー")], g[("b", "マスターボール柄/ミラー仕様")])
        self.assertEqual(len(set(g.values())), 4)  # 通常・マスターボール・1ED・再販

    def test_descriptive_words_are_ignored_when_each_shop_has_one_row(self):
        g = self.groups(a=["RR仕様"], b=[""], c=["キラ"])
        self.assertEqual(len(set(g.values())), 1)

    def test_descriptive_words_tell_rows_apart_when_a_shop_has_several(self):
        g = self.groups(a=["ジムチャレンジ"], b=["ジムチャレンジ通常", "ジムチャレンジ網柄"])
        self.assertEqual(len(set(g.values())), 3)  # どれと同じか分からないので、まとめない

    def test_cross_shop_compares_only_the_same_variant(self):
        a = [price("1", name="ゲンガー", number="094/165", variant="マスターボールミラー", buy=85000)]
        b = [price("2", name="ゲンガー", number="094/165", variant="", buy=0, sell=500),
             price("3", name="ゲンガー", number="094/165", variant="マスターボール柄/ミラー仕様", buy=0, sell=60000)]
        rows = compare.cross_shop({"a": a}, {"a": a, "b": b})
        self.assertEqual([(r["sell_variant"], r["gap"]) for r in rows], [("マスターボール柄/ミラー仕様", 25000)])


class PackTest(unittest.TestCase):
    def loaded(self, stray_pack):
        # 2つの店が同じパック S1a の6枚を扱っている。店 b には、たまたま名前と型番が同じ別パックのカードが1枚ある
        cards = [(f"カード{i}", f"{i:03d}/070") for i in range(1, 7)]
        a = [price(f"a{i}", name=n, number=num, set_code="S1a") for i, (n, num) in enumerate(cards)]
        b = [price(f"b{i}", name=n, number=num, set_code="S1a-M") for i, (n, num) in enumerate(cards)]
        b.append(price("old", name="カード1", number="001/070", set_code=stray_pack))
        return {"a": a, "b": b}

    def test_same_name_and_number_in_another_pack_is_a_different_card(self):
        g = compare.assign_groups(self.loaded("L1-I"))
        self.assertEqual(g[("a", "a0")], g[("b", "b0")])       # S1a と S1a-M は同じパック（枝番は仕様）
        self.assertNotEqual(g[("a", "a0")], g[("b", "old")])   # L1 のカードは別のカード
        self.assertEqual(g[("a", "a1")], "カード2|002/070")     # 分かれないカードのキーは変わらない

    def test_unknown_pack_is_not_split(self):
        g = compare.assign_groups(self.loaded("その他"))
        # パックが分からない行は、別のカードと言い切れないので分けない（同じ店に2行あるので、言葉で見分ける）
        self.assertNotIn("|@", g[("b", "old")])

    def test_pack_family(self):
        self.assertEqual([compare.pack_family(x) for x in ["SV4a-M", "HS-K", "BW8紫", "その他", "XY/171-M", "DPt4-B"]],
                         ["sv4a", "hs", "bw8", "", "xy/171", "dpt4"])

    def test_cross_shop_ignores_another_pack(self):
        loaded = self.loaded("L1-I")
        loaded["a"][0] = price("a0", name="カード1", number="001/070", set_code="S1a", buy=0, sell=50)
        loaded["b"][-1] = price("old", name="カード1", number="001/070", set_code="L1-I", buy=3000)
        rows = compare.cross_shop(loaded, loaded)
        self.assertEqual([r["buy_set"] for r in rows], ["S1a-M"])  # 同じパックどうしだけ。L1 の買取と S1a の販売は比べない


class ParallelFetchTest(unittest.TestCase):
    def test_shops_are_fetched_at_the_same_time_and_one_failure_does_not_stop_the_others(self):
        import threading
        from unittest import mock

        from buylist_watch import cli

        gate = threading.Barrier(2, timeout=5)  # 2店が同時に動いていなければ、ここで時間切れになる

        class Good:
            def __init__(self, item):
                self.item = item

            def fetch(self, fetcher, max_pages=None):
                gate.wait()
                yield price(self.item, buy=1000)

        class Bad:
            def fetch(self, fetcher, max_pages=None):
                raise RuntimeError("403")
                yield

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(cli.SOURCES, {"a": Good("1"), "b": Good("2"), "c": Bad()}, clear=True):
            code = cli.main(["--data-dir", tmp, "fetch", "--delay", "0"])
            self.assertEqual(code, 1)  # 1店が失敗したことは終了コードで伝える
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["a", "b"])


class ShrinkGuardTest(unittest.TestCase):
    def test_big_drop_in_count_is_not_saved_unless_forced(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            full = [price(str(i), buy=1000) for i in range(10)]
            store.save(data, "cardrush", full, "2026-11-11T09:00:00+09:00")
            with self.assertRaises(store.ShrinkError):
                store.save(data, "cardrush", full[:5], "2026-11-12T09:00:00+09:00")
            self.assertEqual(len(store.read_latest(data / "cardrush" / "latest.csv")), 10)  # 前回のまま
            self.assertFalse((data / "cardrush" / "changes").exists())
            meta = json.loads((data / "cardrush" / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["fetched_at"], "2026-11-11T09:00:00+09:00")  # 取得日時は保存できたときのまま
            self.assertEqual(meta["held"], {"since": "2026-11-12T09:00:00+09:00", "last": "2026-11-12T09:00:00+09:00", "count": 5, "times": 1})
            store.save(data, "cardrush", full[:8], "2026-11-12T09:00:00+09:00")  # 少しの減少は保存する
            meta = store.save(data, "cardrush", full[:3], "2026-11-12T12:00:00+09:00", force=True)
            self.assertEqual(meta["count"], 3)


class ShrinkRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.full = [price(str(i), buy=1000) for i in range(10)]
        store.save(self.data, "cardrush", self.full, "2026-11-11T09:00:00+09:00")

    def meta(self):
        return json.loads((self.data / "cardrush" / "meta.json").read_text(encoding="utf-8"))

    def test_hold_is_cleared_when_the_list_comes_back(self):
        with self.assertRaises(store.ShrinkError):
            store.save(self.data, "cardrush", self.full[:5], "2026-11-12T11:40:00+09:00")
        store.save(self.data, "cardrush", self.full, "2026-11-12T11:50:00+09:00")
        self.assertNotIn("held", self.meta())
        self.assertFalse((self.data / "cardrush" / "changes").exists())  # 掲載終了は1件も記録されない

    def test_shrink_that_lasts_a_day_is_accepted(self):
        for at in ("2026-11-12T09:00:00+09:00", "2026-11-12T21:00:00+09:00"):
            with self.assertRaises(store.ShrinkError):
                store.save(self.data, "cardrush", self.full[:5], at)
        self.assertEqual(self.meta()["held"]["times"], 2)
        meta = store.save(self.data, "cardrush", self.full[:5], "2026-11-13T09:00:00+09:00")  # 24時間続いたので保存する
        self.assertEqual((meta["count"], meta["changes"]), (5, 5))
        self.assertNotIn("held", self.meta())

    def test_fetch_waits_and_retries_when_the_list_is_half_updated(self):
        from unittest import mock

        from buylist_watch import cli

        full = self.full

        class Shop:
            calls = 0

            def fetch(self, fetcher, max_pages=None):
                Shop.calls += 1
                yield from (full[:5] if Shop.calls == 1 else full)  # 1回目だけ更新途中の状態

        with mock.patch.dict(cli.SOURCES, {"cardrush": Shop()}, clear=True), mock.patch("time.sleep") as sleep:
            code = cli.main(["--data-dir", str(self.data), "fetch", "--delay", "0", "--shrink-wait", "600"])
        self.assertEqual((code, Shop.calls), (0, 2))
        sleep.assert_called_once_with(600)
        self.assertNotIn("held", self.meta())


class SameDayTest(unittest.TestCase):
    def test_second_fetch_on_the_same_day_keeps_morning_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            store.save(data, "cardrush", [price("1", buy=1000), price("2", buy=2000), price("3", buy=3000)], "2026-11-11T09:00:00+09:00")
            store.save(data, "cardrush", [price("1", buy=1500), price("2", buy=2500), price("3", buy=3000), price("4", buy=400)],
                       "2026-11-12T09:00:00+09:00")
            store.save(data, "cardrush", [price("1", buy=1500), price("2", buy=2000), price("3", buy=3300)], "2026-11-12T13:00:00+09:00")
            with (data / "cardrush" / "changes" / "2026-11-12.csv").open(encoding="utf-8", newline="") as f:
                got = {r["item_id"]: (r["change"], r["old_buy"], r["new_buy"]) for r in csv.DictReader(f)}
            # 1: 朝の値上げが残る。2: 朝上がって昼に戻ったので消える。3: 昼の値上げ。4: 朝に載って昼に消えたので記録しない
            self.assertEqual(got, {"1": ("up", "1000", "1500"), "3": ("up", "3000", "3300")})


class SiteTest(unittest.TestCase):
    def test_build_data_has_items_movers_and_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            day1 = [price("1", name="スターミー", number="005/016", buy=20000), price("2", buy=500), price("3", buy=9000)]
            day2 = [price("1", name="スターミー", number="005/016", buy=50000), price("2", buy=600)]
            store.save(data, "cardrush", day1, "2026-11-10T05:00:00+09:00")
            store.save(data, "cardrush", day2, "2026-11-11T05:00:00+09:00", force=True)  # 3件から2件への減少を通す
            store.save(data, "hareruya2", [price("9", name="スターミー", number="005/016", buy=0, sell=30000)],
                       "2026-11-11T05:00:00+09:00")
            out = site.build_data(data, min_buy=1000)
            # 買取が少額の行は載せない。ただし、他店が買い取っているカードは買取なしの店の行も載せる
            # 値動きのあったカード（id 2）は少額でも載せる
            self.assertEqual([(i[0], i[1], i[7], i[8]) for i in out["items"]], [(0, "1", 50000, 0), (0, "2", 600, 0), (1, "9", 0, 30000)])
            moves = {(m[2], m[7], m[8]) for m in out["movers"]}
            self.assertEqual(moves, {("up", 20000, 50000), ("up", 500, 600), ("removed", 9000, 0)})  # 少額の値上げも載せる
            self.assertEqual(out["history"], {"0:1": [["", 20000], ["2026-11-11", 50000]], "0:2": [["", 500], ["2026-11-11", 600]]})
            self.assertEqual(out["cross"][0][10], 20000)
            self.assertEqual(out["generated_at"], "2026-11-11T05:00:00+09:00")
            self.assertEqual(out["shops"][0]["since"], "2026-11-10T05:00:00+09:00")  # 記録を始めた日時は最初の取得のまま

    def test_shop_name_and_link_come_from_the_source_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            store.save(Path(tmp), "cardrush", [price("1")], "2026-11-11T05:00:00+09:00")
            shops = site.build_data(Path(tmp))["shops"]
            # 店の並び順は、画面が履歴やグラフの色を引くときの番号になる。新しい店は最後に足す
            self.assertEqual([s["id"] for s in shops][:3], ["cardrush", "hareruya2", "yuyutei"])
            self.assertEqual([s["id"] for s in shops], list(SOURCES))
            self.assertEqual(shops[0]["label"], "カードラッシュ")
            self.assertEqual(shops[0]["link"], {"text": "カードラッシュの買取表", "url": "https://cardrush.media/pokemon/buying_prices?name={name}"})
            for s in shops:
                self.assertTrue(s["label"])
                self.assertTrue(s["link"] is None or "{name}" in s["link"]["url"] or "{word}" in s["link"]["url"])

    def test_build_writes_history_to_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, web, out = Path(tmp) / "data", Path(tmp) / "web", Path(tmp) / "out"
            web.mkdir()
            (web / "index.html").write_text("<html></html>", encoding="utf-8")
            store.save(data, "cardrush", [price("1", buy=20000)], "2026-11-10T05:00:00+09:00")
            store.save(data, "cardrush", [price("1", buy=50000)], "2026-11-11T05:00:00+09:00")
            site.build(data, web, out)
            self.assertNotIn("history", json.loads((out / "data.json").read_text(encoding="utf-8")))
            self.assertEqual(json.loads((out / "history.json").read_text(encoding="utf-8")), {"0:1": [["", 20000], ["2026-11-11", 50000]]})

    def test_build_copies_page_and_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "web" / "index.html").write_text("<!DOCTYPE html>", encoding="utf-8")
            store.save(root / "data", "cardrush", [price("1")], "2026-11-11T05:00:00+09:00")
            site.build(root / "data", root / "web", root / "_site")
            self.assertTrue((root / "_site" / "index.html").exists())
            self.assertEqual(json.loads((root / "_site" / "data.json").read_text(encoding="utf-8"))["shops"][0]["count"], 1)


if __name__ == "__main__":
    unittest.main()
