"""ทดสอบสคริปต์อัปเดตแบบออฟไลน์: python scripts/test_update.py"""
import copy, importlib.util, json, os, random, shutil, tempfile, unittest, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("u", os.path.join(HERE, "update_draws.py"))
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)


def fake_api(date_th, seed=1, **over):
    rnd = random.Random(seed)
    num = lambda w, k: ["".join(rnd.choice("0123456789") for _ in range(w)) for _ in range(k)]
    p = lambda i, n, k, w=6: {"id": i, "name": i, "reward": "0", "amount": k, "number": num(w, k)}
    obj = {"status": "success", "response": {"date": date_th, "endpoint": "x",
           "prizes": [p("prizeFirst", "", 1), p("prizeSecond", "", 5), p("prizeThird", "", 10), p("prizeForth", "", 50), p("prizeFifth", "", 100)],
           "runningNumbers": [p("runningNumberFrontThree", "", 2, 3), p("runningNumberBackThree", "", 2, 3), p("runningNumberBackTwo", "", 1, 2)]}}
    f = obj["response"]["prizes"][0]["number"][0]
    obj["response"]["prizes"].append({"id": "prizeFirstNear", "name": "n", "reward": "0", "amount": 2, "number": [str(int(f) - 1).zfill(6), str(int(f) + 1).zfill(6)]})
    for k, v in over.items():
        obj["response"][k] = v
    return obj


class T(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "data"))
        shutil.copy(os.path.join(u.ROOT, "data", "draws.json"), os.path.join(self.tmp, "data", "draws.json"))
        u.JSON_PATH = os.path.join(self.tmp, "data", "draws.json")
        u.JS_PATH = os.path.join(self.tmp, "data", "draws.js")
        self.src = os.path.join(self.tmp, "src.json")
        self.before = self.load(u.JSON_PATH)
        self._orig = (u.bangkok_today, u.fetch_source)

    def tearDown(self):
        u.bangkok_today, u.fetch_source = self._orig
        shutil.rmtree(self.tmp)

    @staticmethod
    def load(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def run_with(self, obj):
        with open(self.src, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return u.main(["--source-file", self.src])

    def draws(self):
        return self.load(u.JSON_PATH)["draws"]

    def test_adds_new_draw(self):
        # ตั้ง "วันนี้" ให้เป็นหลังงวดจำลองเพื่อให้ตรวจวันที่ในอนาคตผ่าน
        u.bangkok_today = lambda: datetime.date(2026, 12, 2)
        self.assertEqual(self.run_with(fake_api("1 ธันวาคม 2569")), 0)
        d = self.draws()
        self.assertEqual(len(d), 400); self.assertEqual(d[-1]["draw_date"], "2026-12-01")
        self.assertEqual(d[-1]["draw_date_th"], "1 ธันวาคม 2569"); self.assertEqual(d[-1]["draw_date_be"], "2569-12-01")
        self.assertEqual(d[:399], self.before["draws"])  # ข้อมูลเดิมไม่ถูกแตะ
        with open(u.JS_PATH, encoding="utf-8") as f:
            js = f.read()
        self.assertEqual(json.loads(js.split("window.LOTTERY_DATA = ", 1)[1].rstrip().rstrip(";"))["draws"][-1]["draw_date"], "2026-12-01")

    def test_idempotent(self):
        u.bangkok_today = lambda: datetime.date(2026, 12, 2)
        self.run_with(fake_api("1 ธันวาคม 2569"))
        with open(u.JSON_PATH, encoding="utf-8") as f:
            snap = f.read()
        self.assertEqual(self.run_with(fake_api("1 ธันวาคม 2569", seed=7)), 0)  # งวดเดิมแต่ตัวเลขต่างกัน: ต้องไม่ทับ
        with open(u.JSON_PATH, encoding="utf-8") as f:
            self.assertEqual(f.read(), snap)

    def test_holiday_shift_accepted(self):
        u.bangkok_today = lambda: datetime.date(2027, 5, 3)
        self.assertEqual(self.run_with(fake_api("2 พฤษภาคม 2570")), 0)
        self.assertEqual(self.draws()[-1]["draw_date"], "2027-05-02")

    def test_old_draw_ignored(self):
        self.assertEqual(self.run_with(fake_api("1 พฤศจิกายน 2569")), 0)
        self.assertEqual(self.draws(), self.before["draws"])

    def test_rejects_bad_data(self):
        u.bangkok_today = lambda: datetime.date(2026, 12, 2)
        bad = fake_api("1 ธันวาคม 2569"); bad["response"]["prizes"][4]["number"].pop()      # รางวัลที่ 5 ขาด 1 ตัว
        self.assertEqual(self.run_with(bad), 1)
        bad = fake_api("1 ธันวาคม 2569"); bad["response"]["prizes"][0]["number"][0] = "12345"  # 5 หลัก
        self.assertEqual(self.run_with(bad), 1)
        bad = fake_api("1 ธันวาคม 2569"); bad["response"]["runningNumbers"].pop()           # ขาดเลขท้าย 2 ตัว
        self.assertEqual(self.run_with(bad), 1)
        self.assertEqual(self.run_with(fake_api("10 ธันวาคม 2569")), 1)                      # วันที่ไม่ใช่ช่วงออกรางวัล
        self.assertEqual(self.run_with(fake_api("ไม่มีวันที่")), 1)
        self.assertEqual(self.draws(), self.before["draws"])                                  # ไม่มีการเขียนไฟล์เลย

    def test_rejects_future_draw(self):
        u.bangkok_today = lambda: datetime.date(2026, 11, 20)
        self.assertEqual(self.run_with(fake_api("1 ธันวาคม 2569")), 1)

    def test_manual_draw_json(self):
        u.bangkok_today = lambda: datetime.date(2026, 12, 2)
        rec = u.parse_api(fake_api("1 ธันวาคม 2569"))
        p = os.path.join(self.tmp, "m.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        self.assertEqual(u.main(["--draw-json", p]), 0)
        self.assertEqual(self.draws()[-1]["draw_date"], "2026-12-01")

    def test_manual_short_form(self):
        u.bangkok_today = lambda: datetime.date(2026, 12, 2)
        rec = {k: v for k, v in u.parse_api(fake_api("1 ธันวาคม 2569")).items() if k in u.SHAPE or k == "draw_date"}
        p = os.path.join(self.tmp, "short.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        self.assertEqual(u.main(["--draw-json", p]), 0)
        self.assertEqual(self.draws()[-1]["draw_date_th"], "1 ธันวาคม 2569")
        del rec["last_two_digits"]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        self.assertEqual(u.main(["--draw-json", p]), 1)

    def test_network_failure_is_error(self):
        u.fetch_source = lambda: (_ for _ in ()).throw(OSError("offline"))
        self.assertEqual(u.main([]), 1)
        self.assertEqual(self.draws(), self.before["draws"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
