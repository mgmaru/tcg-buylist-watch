import csv
import json
import tempfile
import unittest
from pathlib import Path

from buylist_watch import compare, site, store
from buylist_watch.models import Price
from buylist_watch.sources import cardrush, hareruya2, yuyutei


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
            store.save(data, "cardrush", day2, "2026-11-11T05:00:00+09:00")
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
