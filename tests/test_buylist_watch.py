import json
import tempfile
import unittest
from pathlib import Path

from buylist_watch import compare, site, store
from buylist_watch.models import Price
from buylist_watch.sources import cardrush, hareruya2


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
            self.assertEqual([i[1] for i in out["items"]], ["1"])  # 買取が少額の行は載せない
            kinds = {(m[3], m[2]) for m in out["movers"]}
            self.assertEqual(kinds, {("スターミー", "up"), ("ゴンベ", "removed")})  # 少額の変化は載せない
            self.assertEqual(out["history"], {"0:1": [["", 20000], ["2026-11-11", 50000]]})
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
