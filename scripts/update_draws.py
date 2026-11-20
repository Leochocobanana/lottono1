#!/usr/bin/env python3
"""ตรวจและเพิ่มผลสลากกินแบ่งรัฐบาลงวดใหม่ลงใน data/draws.json (และสร้าง data/draws.js)

ใช้เฉพาะไลบรารีมาตรฐานของ Python (ไม่ต้องติดตั้งอะไรเพิ่ม)
ทำงานแบบ "ซ้ำกี่ครั้งก็ปลอดภัย": ถ้างวดนี้มีอยู่แล้ว จะไม่ทำอะไร
ถ้าข้อมูลที่ดึงมาไม่ครบหรือผิดรูปแบบ จะไม่เขียนไฟล์ และจบด้วย exit code 1 (GitHub จะส่งอีเมลแจ้งเตือน)

วิธีใช้:
  python scripts/update_draws.py                      ดึงงวดล่าสุดจากอินเทอร์เน็ตแล้วเพิ่มถ้าเป็นงวดใหม่
  python scripts/update_draws.py --dry-run            ตรวจอย่างเดียว ไม่เขียนไฟล์
  python scripts/update_draws.py --source-file x.json ใช้ไฟล์ (รูปแบบเดียวกับ API) แทนการดึงจากเน็ต
  python scripts/update_draws.py --draw-json y.json   เพิ่มงวดด้วยมือ (รูปแบบเดียวกับใน draws.json หรือแบบย่อที่มี draw_date + 9 รางวัล)
  python scripts/update_draws.py --rebuild-js         สร้าง data/draws.js ใหม่จาก draws.json เท่านั้น
"""
import argparse, datetime, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "data", "draws.json")
JS_PATH = os.path.join(ROOT, "data", "draws.js")
SOURCE_URL = os.environ.get("LOTTO_SOURCE_URL", "https://lotto.api.rayriffy.com/latest")

TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
# ชื่อรางวัลในไฟล์ของเรา -> (จำนวนรางวัล, จำนวนหลัก)
SHAPE = {"first_prize": (1, 6), "near_first_prize": (2, 6), "second_prize": (5, 6),
         "third_prize": (10, 6), "fourth_prize": (50, 6), "fifth_prize": (100, 6),
         "front_three_digits": (2, 3), "last_three_digits": (2, 3), "last_two_digits": (1, 2)}
# รหัสรางวัลของ API -> ชื่อในไฟล์ของเรา
API_IDS = {"prizeFirst": "first_prize", "prizeFirstNear": "near_first_prize", "prizeSecond": "second_prize",
           "prizeThird": "third_prize", "prizeForth": "fourth_prize", "prizeFifth": "fifth_prize",
           "runningNumberFrontThree": "front_three_digits", "runningNumberBackThree": "last_three_digits",
           "runningNumberBackTwo": "last_two_digits"}


class UpdateError(Exception):
    pass


def bangkok_today():
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)).date()


def load_data():
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


def thai_date_to_iso(text):
    m = re.search(r"(\d{1,2})\s*(" + "|".join(TH_MONTHS) + r")\s*(\d{4})", text or "")
    if not m:
        raise UpdateError("อ่านวันที่งวดไม่ได้จากข้อความ: %r" % (text,))
    day, month, year = int(m.group(1)), TH_MONTHS.index(m.group(2)) + 1, int(m.group(3))
    if year > 2400:
        year -= 543
    return datetime.date(year, month, day).isoformat()


def parse_api(obj):
    """แปลงผลจาก API (รูปแบบ response.date / prizes / runningNumbers) เป็นรูปแบบของเรา"""
    r = obj.get("response", obj)
    iso = thai_date_to_iso(str(r.get("date", "")))
    found = {}
    for item in list(r.get("prizes", [])) + list(r.get("runningNumbers", [])):
        key = API_IDS.get(item.get("id"))
        if key:
            found[key] = [str(n).strip() for n in item.get("number", [])]
    missing = [k for k in SHAPE if k not in found]
    if missing:
        ids = [i.get("id") for i in list(r.get("prizes", [])) + list(r.get("runningNumbers", []))]
        raise UpdateError("ข้อมูลจาก API ขาดรางวัล %s (รหัสที่พบ: %s)" % (missing, ids))
    return build_record(iso, found)


def build_record(iso, found):
    y, m, d = (int(x) for x in iso.split("-"))
    rec = {"draw_date": iso, "draw_date_be": "%04d-%02d-%02d" % (y + 543, m, d),
           "draw_date_th": "%d %s %d" % (d, TH_MONTHS[m - 1], y + 543), "year_be": y + 543}
    for k in ("first_prize", "near_first_prize", "second_prize", "third_prize", "fourth_prize", "fifth_prize",
              "front_three_digits", "last_three_digits", "last_two_digits"):
        rec[k] = sorted(found[k])
    rec["glo_result_pdf"] = None
    return rec


def validate(rec, last_date, today):
    for k, (count, width) in SHAPE.items():
        v = rec.get(k)
        if not isinstance(v, list) or len(v) != count:
            raise UpdateError("%s ต้องมี %d รายการ แต่ได้ %s" % (k, count, None if v is None else len(v)))
        for n in v:
            if not (isinstance(n, str) and n.isdigit() and len(n) == width):
                raise UpdateError("%s มีค่าผิดรูปแบบ: %r (ต้องเป็นตัวเลข %d หลัก)" % (k, n, width))
    if len(set(rec["fifth_prize"] + rec["fourth_prize"] + rec["third_prize"] + rec["second_prize"])) < 120:
        raise UpdateError("เลขซ้ำกันมากผิดปกติ น่าจะเป็นข้อมูลที่ผิดพลาด")
    try:
        dt = datetime.date.fromisoformat(rec["draw_date"])
    except Exception:
        raise UpdateError("วันที่งวดผิดรูปแบบ: %r" % (rec.get("draw_date"),))
    if not (dt.day in (1, 2, 3, 4) or dt.day in (16, 17, 18, 19)):
        raise UpdateError("วันที่ %s ไม่ใช่ช่วงวันออกรางวัลปกติ (1-4 หรือ 16-19) จึงไม่เพิ่มอัตโนมัติ" % rec["draw_date"])
    if dt > today + datetime.timedelta(days=1):
        raise UpdateError("วันที่งวด %s อยู่ในอนาคต" % rec["draw_date"])
    return dt


def fetch_source():
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "lotto-app-updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def dumps(data):
    head = {k: v for k, v in data.items() if k != "draws"}
    head_txt = json.dumps(head, ensure_ascii=False, indent=1)[:-2]  # ตัด "\n}" ท้าย
    rows = ",\n".join(" " + json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in data["draws"])
    return head_txt + ',\n "draws": [\n' + rows + "\n ]\n}\n"


def save(data):
    data["draws"].sort(key=lambda d: d["draw_date"])
    data["draw_count"] = len(data["draws"])
    data["first_draw"] = data["draws"][0]["draw_date"]
    data["last_draw"] = data["draws"][-1]["draw_date"]
    data["generated"] = bangkok_today().isoformat()
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(dumps(data))
    os.replace(tmp, JSON_PATH)
    write_js(data)


def write_js(data=None):
    data = data or load_data()
    with open(JS_PATH, "w", encoding="utf-8") as f:
        f.write("// สร้างอัตโนมัติจาก data/draws.json ห้ามแก้ไขไฟล์นี้ด้วยมือ\nwindow.LOTTERY_DATA = " +
                json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source-file")
    ap.add_argument("--draw-json")
    ap.add_argument("--rebuild-js", action="store_true")
    a = ap.parse_args(argv)
    if a.rebuild_js:
        write_js(); print("สร้าง data/draws.js ใหม่แล้ว"); return 0
    data = load_data()
    last = data["draws"][-1]["draw_date"]
    try:
        if a.draw_json:
            with open(a.draw_json, encoding="utf-8") as f:
                rec = json.load(f)
            if "draw_date_th" not in rec:  # รูปแบบย่อ: มีแค่ draw_date กับรางวัลต่างๆ
                if not all(k in rec for k in SHAPE) or "draw_date" not in rec:
                    raise UpdateError("ข้อมูลที่วางต้องมี draw_date และครบทั้ง 9 รายการรางวัล: %s" % ", ".join(SHAPE))
                rec = build_record(rec["draw_date"], rec)
            for k in SHAPE:
                if isinstance(rec.get(k), list):
                    rec[k] = sorted(str(n).strip() for n in rec[k])
            rec.setdefault("glo_result_pdf", None)
        elif a.source_file:
            with open(a.source_file, encoding="utf-8") as f:
                rec = parse_api(json.load(f))
        else:
            rec = parse_api(fetch_source())
        dt = validate(rec, last, bangkok_today())
    except UpdateError as e:
        print("ข้อผิดพลาด: %s\nไม่ได้แก้ไขข้อมูลใดๆ" % e, file=sys.stderr); return 1
    except Exception as e:
        print("ดึงข้อมูลไม่สำเร็จ: %s: %s\nไม่ได้แก้ไขข้อมูลใดๆ" % (type(e).__name__, e), file=sys.stderr); return 1
    if rec["draw_date"] in {d["draw_date"] for d in data["draws"]}:
        print("งวด %s มีอยู่แล้ว ไม่ต้องอัปเดต (ล่าสุดในระบบ: %s)" % (rec["draw_date"], last)); return 0
    if rec["draw_date"] < last:
        print("แหล่งข้อมูลยังเป็นงวด %s ซึ่งเก่ากว่าที่มีอยู่ (%s) ไม่ต้องอัปเดต" % (rec["draw_date"], last)); return 0
    if a.dry_run:
        print("[ทดลอง] จะเพิ่มงวด %s (ผลรางวัลที่ 1: %s)" % (rec["draw_date"], rec["first_prize"][0])); return 0
    data["draws"].append(rec)
    save(data)
    print("เพิ่มงวด %s แล้ว (ผลรางวัลที่ 1: %s, เลขท้าย 2 ตัว: %s) รวม %d งวด" % (
        rec["draw_date"], rec["first_prize"][0], rec["last_two_digits"][0], len(data["draws"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
