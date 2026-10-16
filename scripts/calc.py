#!/usr/bin/env python3
"""賃貸物件チェック用の計算スクリプト（標準ライブラリのみ）。

サブコマンド:
  screen 希望条件（賃料・面積・徒歩・築年・契約期間）による一次判定
  geo   物件と周辺施設の距離・方角、窓の正面にあるか、深掘り対象かを判定
  cost  初期費用の合計と毎月の支払額を計算
  term  定期借家の入居日から満了日までの残り期間を計算
  kids  保育園など子育て施設の徒歩分数・園数を集計し、子育て環境を判定

使い方は各サブコマンドの --help を参照。
"""
import argparse
import calendar
import json
import math
import sys
from datetime import date, timedelta

# ---------------------------------------------------------------- geo

DIRS_16 = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
           "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]

DIR_TO_DEG = {
    "北": 0, "北東": 45, "東": 90, "南東": 135, "南": 180, "南西": 225, "西": 270, "北西": 315,
    "北北東": 22.5, "東北東": 67.5, "東南東": 112.5, "南南東": 157.5,
    "南南西": 202.5, "西南西": 247.5, "西北西": 292.5, "北北西": 337.5,
    "N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315,
}


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def to_16(deg):
    return DIRS_16[int((deg + 11.25) // 22.5) % 16]


def parse_facing(s):
    s = s.strip()
    if s in DIR_TO_DEG:
        return float(DIR_TO_DEG[s])
    s2 = s.replace("向き", "")
    if s2 in DIR_TO_DEG:
        return float(DIR_TO_DEG[s2])
    return float(s) % 360


def angle_diff(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


# 施設名から「重い業種」（騒音・粉じん・大型車の出入りが多い）を拾う予備の判定。
# 名前だけでは拾えない（「○○興業」「英語表記」など）ため、本来は呼び出し側が業種を確認して
# "heavy": true/false を明示する。明示があればそれを最優先する。
HEAVY_KEYWORDS = ["生コン", "コンクリート", "建材", "砕石", "骨材", "アスファルト", "清掃工場", "焼却",
                  "ごみ処理", "ゴミ処理", "産業廃棄物", "産廃", "リサイクルセンター", "首都高", "高速", "高架",
                  "物流センター", "配送センター", "物流",
                  "concrete", "ready mix", "ready-mix", "asphalt", "aggregate", "waste", "incinerat",
                  "recycling", "expressway", "logistics", "distribution center"]
# Googleの種別（places_search の types）で重い業種の可能性があるもの
HEAVY_TYPES = {"manufacturer", "general_contractor", "factory", "industrial", "warehouse",
               "trucking_company", "moving_company", "waste_management", "recycling_center"}
# 名前に含まれていれば重い業種から外す（倉庫でも人の出入り程度で済むもの）
LIGHT_KEYWORDS = ["トランクルーム", "レンタル収納", "レンタル倉庫", "コンテナ収納", "self storage", "キッザニア"]


def heavy_reason(f):
    """重い業種かどうか、確度、理由を返す。

    確度 "sure"：指定または名前で判断。見送り候補の判定に使える。
    確度 "type"：Google種別だけからの推定（小さな工務店なども含まれる）。深掘り対象にはするが、
                 業種を確認して "heavy" を指定するまで見送り候補にはしない。
    """
    if "heavy" in f:
        return bool(f["heavy"]), "sure", ("指定: 重い業種" if f["heavy"] else "指定: 対象外")
    name = f.get("name", "")
    low = name.lower()
    if any(k.lower() in low for k in LIGHT_KEYWORDS):
        return False, "sure", "名前から軽い施設と判断"
    for k in HEAVY_KEYWORDS:
        if k.lower() in low:
            return True, "sure", f"名前に「{k}」"
    hit = HEAVY_TYPES.intersection(f.get("types") or [])
    if hit:
        return True, "type", "Google種別 " + ",".join(sorted(hit)) + "（業種未確認）"
    return False, "sure", ""


def cmd_geo(args):
    facilities = json.loads(args.facilities)
    facings = {}
    for item in (args.window or []):
        label, _, val = item.partition("=")
        facings[label] = parse_facing(val)
    rows = []
    for f in facilities:
        dist = haversine_m(args.lat, args.lon, f["lat"], f["lon"])
        brg = bearing_deg(args.lat, args.lon, f["lat"], f["lon"])
        row = {"name": f["name"], "distance_m": round(dist), "bearing_deg": round(brg, 1),
               "direction": to_16(brg), "windows": {}}
        facing_hit = False
        for label, face in facings.items():
            diff = angle_diff(brg, face)
            if diff <= 45:
                verdict = "正面"
                facing_hit = True
            elif diff <= 90:
                verdict = "斜め"
                facing_hit = True
            else:
                verdict = "背面"
            row["windows"][label] = {"angle_from_window": round(diff, 1), "verdict": verdict}
        heavy, certainty, reason = heavy_reason(f)
        row["heavy"] = heavy
        row["heavy_certainty"] = certainty
        row["heavy_reason"] = reason
        # 深掘り対象: 近く(focus)で窓側にある施設、または重い業種で heavy_radius 以内・窓側
        if not facings:
            facing_hit = True
        row["investigate"] = bool(facing_hit and (dist <= args.focus_radius or (heavy and dist <= args.heavy_radius)))
        front = any(v["verdict"] == "正面" for v in row["windows"].values())
        row["fatal_candidate"] = bool(heavy and certainty == "sure" and front and dist <= args.heavy_radius)
        row["needs_type_check"] = bool(heavy and certainty == "type" and front and dist <= args.heavy_radius)
        rows.append(row)
    rows.sort(key=lambda r: r["distance_m"])
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            w = "、".join(f"{k}:{v['verdict']}({v['angle_from_window']}°)" for k, v in r["windows"].items())
            if r["fatal_candidate"]:
                mark = "✖見送り候補"
            elif r["needs_type_check"]:
                mark = "？業種確認"
            elif r["investigate"]:
                mark = "★深掘り"
            else:
                mark = "　対象外"
            why = f" / 重い業種: {r['heavy_reason']}" if r["heavy"] else ""
            print(f"{mark} {r['name']}: {r['distance_m']}m / {r['direction']}({r['bearing_deg']}°) / {w}{why}")
    print(f"\n判定基準: 正面=窓の向き±45度、斜め=±90度。深掘り=窓側（正面・斜め）で{args.focus_radius:g}m以内、"
          f"または重い業種（生コン・清掃工場・首都高など）で{args.heavy_radius:g}m以内。"
          "重い業種は \"heavy\" の指定を優先し、指定がなければ名前・Google種別から推定。"
          "？業種確認=Google種別だけで重い業種の可能性があり窓の正面にある施設（業種を調べて heavy を指定し再実行）。"
          f"見送り候補=重い業種が窓の正面で{args.heavy_radius}m以内。"
          "座標は代表点。大規模マンションは住戸のある棟の座標を使うこと。", file=sys.stderr)


# ---------------------------------------------------------------- screen

def cmd_screen(a):
    results = []

    def add(item, ok, detail, level=None):
        results.append((item, level or ("OK" if ok else "NG"), detail))

    if a.monthly is not None:
        over = a.monthly - a.max_monthly
        if over <= 0:
            add("賃料（管理費込み）", True, f"{a.monthly:,}円 ≤ 上限{a.max_monthly:,}円")
        elif over <= a.max_monthly * a.rent_tolerance:
            add("賃料（管理費込み）", False, f"{a.monthly:,}円（上限を{over:,}円超過・許容幅内）", "注意")
        else:
            add("賃料（管理費込み）", False, f"{a.monthly:,}円（上限を{over:,}円超過）")
    if a.area is not None:
        add("専有面積", a.area >= a.min_area, f"{a.area}㎡（基準{a.min_area}㎡以上）")
    if a.walk is not None:
        add("駅徒歩", a.walk <= a.max_walk, f"{a.walk}分（基準{a.max_walk}分以内）")
    if a.built:
        y, m = map(int, a.built.split("-")[:2])
        ref = date.fromisoformat(a.ref_date) if a.ref_date else date.today()
        age = ref.year - y - (1 if ref.month < m else 0)
        add("築年数", age <= a.max_age, f"築{age}年（{a.built}築、基準{a.max_age}年以内）")
        add("耐震基準", (y, m) >= (1981, 6), "新耐震（1981年6月以降築）" if (y, m) >= (1981, 6) else "旧耐震の可能性（建築確認日を確認）")
    if a.lease:
        if a.lease == "fixed":
            if a.term_months is None:
                add("契約期間", False, "定期借家：期間不明（term サブコマンドで計算して渡す）", "要確認")
            else:
                add("契約期間", a.term_months >= a.min_term, f"定期借家 残り{a.term_months}ヶ月（基準{a.min_term}ヶ月以上）")
        else:
            add("契約期間", True, "普通借家")
    print(f"使用した基準: 賃料上限{a.max_monthly:,}円（超過{a.rent_tolerance:.0%}までは注意）／面積{a.min_area}㎡以上／"
          f"駅徒歩{a.max_walk}分以内／築{a.max_age}年以内／定期借家{a.min_term:g}ヶ月以上")
    for item, level, detail in results:
        print(f"[{level}] {item}: {detail}")
    ng = [r for r in results if r[1] == "NG"]
    print("\n一次判定: " + ("見送り候補（NGあり）" if ng else "通過（詳細チェックへ）"))


# ---------------------------------------------------------------- cost

def prorate(amount, move_in):
    days_in_month = calendar.monthrange(move_in.year, move_in.month)[1]
    days = days_in_month - move_in.day + 1
    return round(amount * days / days_in_month), days, days_in_month


def cmd_cost(a):
    base = a.rent + a.admin  # 賃料等（共益費込み）
    items = []

    def add(name, value, note=""):
        items.append((name, round(value), note))

    add("敷金", a.rent * a.deposit_months, f"{a.deposit_months}ヶ月（退去時に原状回復費を引いて返還）")
    add("礼金", a.rent * a.key_money_months, f"{a.key_money_months}ヶ月")
    brokerage = a.rent * a.brokerage_months * (1 + a.tax_rate) if a.brokerage_tax_excluded else a.rent * a.brokerage_months
    add("仲介手数料", brokerage, f"{a.brokerage_months}ヶ月" + ("（税別指定→税込換算）" if a.brokerage_tax_excluded else "（税込）"))
    if a.guarantee_initial_pct is not None:
        add("保証料（初回）", base * a.guarantee_initial_pct / 100, f"賃料等の{a.guarantee_initial_pct}%")
    if a.guarantee_initial_yen:
        add("保証料（初回・定額）", a.guarantee_initial_yen)
    add("前家賃（翌月分・賃料等）", base, "")
    if a.move_in:
        mi = date.fromisoformat(a.move_in)
        pr, days, dim = prorate(base, mi)
        add("日割り家賃", pr, f"{mi.isoformat()}から{days}/{dim}日")
    for other in (a.other or []):
        name, _, val = other.partition("=")
        add(name, float(val))
    if a.fire_insurance:
        add("火災保険", a.fire_insurance)

    total = sum(v for _, v, _ in items)
    rent_prepaid = sum(v for n, v, _ in items if n in ("前家賃（翌月分・賃料等）", "日割り家賃"))
    deposit = round(a.rent * a.deposit_months)
    non_refundable = total - deposit - rent_prepaid
    monthly = base
    monthly_notes = [f"賃料等 {base:,}円"]
    if a.guarantee_monthly_pct:
        g = max(round(base * a.guarantee_monthly_pct / 100), a.guarantee_monthly_min or 0)
        monthly += g
        monthly_notes.append(f"月額保証料 {g:,}円")
    for m in (a.monthly_other or []):
        name, _, val = m.partition("=")
        monthly += float(val)
        monthly_notes.append(f"{name} {int(float(val)):,}円")

    print("【初期費用】")
    for name, v, note in items:
        print(f"  - {name}: {v:,}円" + (f"　※{note}" if note else ""))
    print(f"  合計: {total:,}円")
    print(f"  内訳の性質: 戻らないお金 {non_refundable:,}円 ／ 家賃の前払い {rent_prepaid:,}円 ／ 敷金（返還対象） {deposit:,}円")
    print("【毎月の支払い】")
    print(f"  合計 {int(monthly):,}円（" + "、".join(monthly_notes) + "）")
    print("\n注意: 前家賃・日割りの扱いは会社により異なる（入居月の日割り＋翌月分が一般的）。見積書で確認すること。", file=sys.stderr)


# ---------------------------------------------------------------- term

def months_between(d1, d2):
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        months -= 1
    anchor_y = d1.year + (d1.month - 1 + months) // 12
    anchor_m = (d1.month - 1 + months) % 12 + 1
    anchor_d = min(d1.day, calendar.monthrange(anchor_y, anchor_m)[1])
    rem_days = (d2 - date(anchor_y, anchor_m, anchor_d)).days
    return months, rem_days


def parse_end(s):
    parts = s.split("-")
    if len(parts) == 2:  # YYYY-MM → 月末
        y, m = int(parts[0]), int(parts[1])
        return date(y, m, calendar.monthrange(y, m)[1]), True
    return date.fromisoformat(s), False


def cmd_term(a):
    start = date.fromisoformat(a.move_in)
    end, assumed = parse_end(a.end)
    if end <= start:
        print("満了日が入居日以前です。", file=sys.stderr)
        sys.exit(1)
    # 満了日は契約期間に含まれる（例: 2025-04-01〜2028-03-31 は3年）ので翌日で計算する
    months, days = months_between(start, end + timedelta(days=1))
    total_months = months + days / 30.44
    print(f"入居日 {start.isoformat()} → 満了日 {end.isoformat()}（満了日を含む）" + ("、満了日は月末と仮定" if assumed else ""))
    print(f"残り期間: 約{months // 12}年{months % 12}ヶ月{days}日（約{total_months:.2f}ヶ月）")
    ok = total_months >= a.min_months
    print(f"希望（{a.min_months:g}ヶ月以上）: " + ("満たす" if ok else "満たさない"))


# ---------------------------------------------------------------- kids

NURSERY_KINDS = ["認可", "小規模", "認証", "認可外", "保育不明"]
KIND_ALIASES = {"不明": "保育不明", "認可保育園": "認可", "小規模保育": "小規模", "認証保育所": "認証"}


def hhmm_to_min(s):
    h, _, m = s.strip().partition(":")
    return int(h) * 60 + int(m or 0)


def cmd_kids(a):
    facilities = json.loads(a.facilities)
    count_kinds = [k.strip() for k in a.count_kinds.split(",") if k.strip()]
    need = hhmm_to_min(a.need_until) if a.need_until else None
    rows = []
    for f in facilities:
        kind = KIND_ALIASES.get(f.get("kind", "保育不明"), f.get("kind", "保育不明"))
        dist = haversine_m(a.lat, a.lon, f["lat"], f["lon"])
        walk = dist * a.detour / a.speed
        row = {"name": f["name"], "kind": kind, "distance_m": round(dist), "walk_min": math.ceil(walk),
               "until": f.get("until"), "slots": f.get("slots"), "border": f.get("border")}
        row["late_ok"] = None
        if need is not None and f.get("until"):
            row["late_ok"] = hhmm_to_min(f["until"]) >= need
        rows.append(row)
    rows.sort(key=lambda r: r["distance_m"])
    within = [r for r in rows if r["kind"] in NURSERY_KINDS and r["walk_min"] <= a.max_walk_min]
    counted = [r for r in within if r["kind"] in count_kinds]
    unknown = [r for r in within if r["kind"] == "保育不明"]

    if not within:
        verdict = "NG", f"徒歩{a.max_walk_min}分以内に保育施設が1つもない（見送り候補）"
    elif len(counted) >= a.min_count:
        verdict = "OK", f"徒歩{a.max_walk_min}分以内に{'・'.join(count_kinds)}が{len(counted)}園（基準{a.min_count}園以上）"
    elif unknown:
        verdict = "要分類", (f"徒歩{a.max_walk_min}分以内の保育施設{len(within)}か所のうち{len(unknown)}か所は種別不明。"
                          "区の保育施設一覧で認可かどうかを確認して再実行")
    else:
        verdict = "注意", f"徒歩{a.max_walk_min}分以内の{'・'.join(count_kinds)}は{len(counted)}園（基準{a.min_count}園以上に届かない）"

    if a.json:
        print(json.dumps({"verdict": verdict[0], "detail": verdict[1], "facilities": rows}, ensure_ascii=False, indent=2))
        return
    print(f"使用した基準: 園まで徒歩{a.max_walk_min}分以内に{'・'.join(count_kinds)}が{a.min_count}園以上"
          + (f"／延長保育{a.need_until}まで" if a.need_until else ""))
    print(f"[{verdict[0]}] 保育園: {verdict[1]}")
    print("\n【保育施設（近い順）】")
    shown = [r for r in rows if r["kind"] in NURSERY_KINDS][: a.top]
    for r in shown:
        extra = []
        if r["until"]:
            extra.append(f"〜{r['until']}" + ("" if r["late_ok"] is None else ("" if r["late_ok"] else "（希望時刻に届かない）")))
        if r["slots"] is not None:
            extra.append(f"入所可能数{r['slots']}")
        if r["border"] is not None:
            extra.append(f"ボーダー{r['border']}")
        mark = "○" if r in within else "　"
        print(f" {mark} {r['name']}［{r['kind']}］徒歩約{r['walk_min']}分（直線{r['distance_m']}m）" + ("／" + "／".join(extra) if extra else ""))
    slots = [r["slots"] for r in counted if isinstance(r["slots"], (int, float))]
    if slots:
        print(f"\n徒歩圏の{'・'.join(count_kinds)}の入所可能数（対象年齢クラス）合計: {sum(slots):g}")
    for kind in sorted({r["kind"] for r in rows if r["kind"] not in NURSERY_KINDS}):
        near = next(r for r in rows if r["kind"] == kind)
        print(f"最寄りの{kind}: {near['name']} 徒歩約{near['walk_min']}分（直線{near['distance_m']}m）")
    print(f"\n注意: 徒歩分数は直線距離×{a.detour:g}÷{a.speed:g}m/分の目安（道なりの距離ではない）。"
          "○=徒歩圏内。種別・入所可能数・ボーダーは区の資料で確認した値だけを渡すこと。", file=sys.stderr)


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("geo", help="距離・方角・窓の正面判定")
    g.add_argument("--lat", type=float, required=True, help="物件の緯度")
    g.add_argument("--lon", type=float, required=True, help="物件の経度")
    g.add_argument("--facilities", required=True,
                   help='JSON配列: [{"name":"工場","lat":35.6,"lon":139.8}, ...]')
    g.add_argument("--window", action="append",
                   help="窓の向き。ラベル=方角 の形式（例: リビング=東、寝室=225）。複数指定可")
    g.add_argument("--focus-radius", type=float, default=200, help="窓側で深掘りする距離（m）")
    g.add_argument("--heavy-radius", type=float, default=500, help="重い業種を深掘りする距離（m）")
    g.add_argument("--json", action="store_true", help="JSONで出力")
    g.set_defaults(func=cmd_geo)

    sc = sub.add_parser("screen", help="希望条件による一次判定")
    sc.add_argument("--monthly", type=int, help="賃料＋管理費（円）")
    sc.add_argument("--max-monthly", type=int, required=True, help="賃料上限（管理費込み・円）。criteria.md から渡す")
    sc.add_argument("--rent-tolerance", type=float, default=0.03, help="上限超過を「注意」扱いにする割合（既定3%%）")
    sc.add_argument("--area", type=float, help="専有面積（㎡）")
    sc.add_argument("--min-area", type=float, required=True, help="最低専有面積（㎡）。criteria.md から渡す")
    sc.add_argument("--walk", type=int, help="最寄駅徒歩（分）")
    sc.add_argument("--max-walk", type=int, required=True, help="駅徒歩の上限（分）。criteria.md から渡す")
    sc.add_argument("--built", help="築年月 YYYY-MM")
    sc.add_argument("--max-age", type=int, required=True, help="築年数の上限（年）。criteria.md から渡す")
    sc.add_argument("--ref-date", help="築年数の基準日 YYYY-MM-DD（既定は今日）")
    sc.add_argument("--lease", choices=["normal", "fixed"], help="普通借家 normal / 定期借家 fixed")
    sc.add_argument("--term-months", type=float, help="定期借家の残り期間（ヶ月）")
    sc.add_argument("--min-term", type=float, required=True, help="定期借家の最低期間（ヶ月）。criteria.md から渡す")
    sc.set_defaults(func=cmd_screen)

    c = sub.add_parser("cost", help="初期費用と毎月の支払い")
    c.add_argument("--rent", type=int, required=True, help="賃料（円）")
    c.add_argument("--admin", type=int, default=0, help="管理費・共益費（円）")
    c.add_argument("--deposit-months", type=float, default=0)
    c.add_argument("--key-money-months", type=float, default=0)
    c.add_argument("--brokerage-months", type=float, default=0, help="仲介手数料（ヶ月）")
    c.add_argument("--brokerage-tax-excluded", action="store_true", help="仲介手数料が税別表記なら指定")
    c.add_argument("--tax-rate", type=float, default=0.10)
    c.add_argument("--guarantee-initial-pct", type=float, help="初回保証料（賃料等に対する%%）")
    c.add_argument("--guarantee-initial-yen", type=int, help="初回保証料（定額）")
    c.add_argument("--guarantee-monthly-pct", type=float, help="月額保証料（賃料等に対する%%）")
    c.add_argument("--guarantee-monthly-min", type=int, help="月額保証料の最低額")
    c.add_argument("--fire-insurance", type=int, help="火災保険料（円）")
    c.add_argument("--move-in", help="入居日（賃料発生日） YYYY-MM-DD。日割り計算に使う")
    c.add_argument("--other", action="append", help="その他初期費用 名称=金額（例: 除菌施工料=19800）")
    c.add_argument("--monthly-other", action="append", help="その他の月額費用 名称=金額")
    c.set_defaults(func=cmd_cost)

    t = sub.add_parser("term", help="定期借家の残り期間")
    t.add_argument("--move-in", required=True, help="入居予定日 YYYY-MM-DD")
    t.add_argument("--end", required=True, help="満了日 YYYY-MM-DD または YYYY-MM（月末と仮定）")
    t.add_argument("--min-months", type=float, required=True, help="定期借家の最低期間（ヶ月）。criteria.md から渡す")
    t.set_defaults(func=cmd_term)

    k = sub.add_parser("kids", help="保育園など子育て施設の集計と判定")
    k.add_argument("--lat", type=float, required=True, help="物件の緯度")
    k.add_argument("--lon", type=float, required=True, help="物件の経度")
    k.add_argument("--facilities", required=True,
                   help='JSON配列: [{"name":"○○保育園","lat":35.6,"lon":139.8,"kind":"認可","until":"20:30",'
                        '"slots":6,"border":12}, ...]  kind は 認可/小規模/認証/認可外/保育不明/小児科/公園。'
                        'until（閉所・延長の終了時刻）、slots（対象年齢クラスの入所可能数）、border（ボーダー指数）は任意')
    k.add_argument("--max-walk-min", type=int, required=True, help="園まで徒歩の上限（分）。criteria.md から渡す")
    k.add_argument("--min-count", type=int, required=True, help="徒歩圏に必要な園数。criteria.md から渡す")
    k.add_argument("--count-kinds", default="認可,小規模", help="園数に数える種別（既定: 認可,小規模）")
    k.add_argument("--need-until", help="必要な延長保育の終了時刻 HH:MM（例 19:00）")
    k.add_argument("--detour", type=float, default=1.3, help="直線距離→道のりの係数（既定1.3）")
    k.add_argument("--speed", type=float, default=80, help="徒歩の速さ m/分（既定80、不動産表示の基準）")
    k.add_argument("--top", type=int, default=8, help="一覧に出す保育施設の数")
    k.add_argument("--json", action="store_true", help="JSONで出力")
    k.set_defaults(func=cmd_kids)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
