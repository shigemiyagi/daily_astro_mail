# -*- coding: utf-8 -*-
import os
import swisseph as swe
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# --- 基本設定 ---
EPHE_PATH = 'ephe'
swe.set_ephe_path(EPHE_PATH)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
TO_EMAIL = os.getenv('TO_EMAIL')
FROM_EMAIL = "shigemiyagi@gmail.com" # SendGridで認証した送信元メールアドレスに書き換えてください

# --- 占星術関連の定数 ---
SIGN_NAMES = ["牡羊座", "牡牛座", "双子座", "蟹座", "獅子座", "乙女座", "天秤座", "蠍座", "射手座", "山羊座", "水瓶座", "魚座"]
DEGREES_PER_SIGN = 30
ZODIAC_DEGREES = 360

GEO_CELESTIAL_BODIES = {
    "太陽": swe.SUN, "月": swe.MOON, "水星": swe.MERCURY, "金星": swe.VENUS,
    "火星": swe.MARS, "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS,
    "海王星": swe.NEPTUNE, "冥王星": swe.PLUTO, "ドラゴンヘッド": swe.MEAN_NODE
}
HELIO_CELESTIAL_BODIES = {
    "地球": swe.EARTH, "水星": swe.MERCURY, "金星": swe.VENUS, "火星": swe.MARS,
    "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS, "海王星": swe.NEPTUNE,
    "冥王星": swe.PLUTO
}
ASPECTS = {
    "コンジャンクション (0度)": {"angle": 0, "orb": 8},
    "オポジション (180度)": {"angle": 180, "orb": 8},
    "トライン (120度)": {"angle": 120, "orb": 8},
    "スクエア (90度)": {"angle": 90, "orb": 6},
    "セクスタイル (60度)": {"angle": 60, "orb": 4},
}

JAPAN_NATAL_DATA = {
    "year": 1889, "month": 2, "day": 11,
    "hour": 10, "minute": 30, "second": 0,
    "tz": 9.0
}

# --- 天文計算関数 ---
def get_julian_day(year, month, day, hour, minute, second, tz):
    dt_local = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=tz)))
    dt_utc = dt_local.astimezone(timezone.utc)
    jd_ut, _ = swe.utc_to_jd(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, dt_utc.second, 1)
    return jd_ut

def calculate_celestial_points(jd_ut, is_helio=False):
    points = {}
    iflag = swe.FLG_SWIEPH
    celestial_bodies = HELIO_CELESTIAL_BODIES if is_helio else GEO_CELESTIAL_BODIES
    if is_helio:
        iflag |= swe.FLG_HELCTR
    for name, p_id in celestial_bodies.items():
        res = swe.calc_ut(jd_ut, p_id, iflag)
        points[name] = {'pos': res[0][0]}
    return points

def format_positions_for_ai(title, points):
    lines = [f"### {title}"]
    for name, data in points.items():
        pos = data['pos']
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        lines.append(f"- {name}: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def calculate_aspects_for_ai(title, points1, points2, prefix1="", prefix2=""):
    aspect_list = []
    p1_names, p2_names = list(points1.keys()), list(points2.keys())
    for i in range(len(p1_names)):
        for j in range(len(p2_names)):
            if points1 is points2 and i >= j:
                continue
            p1_name, p2_name = p1_names[i], p2_names[j]
            p1, p2 = points1[p1_name], points2[p2_name]
            angle_diff = abs(p1['pos'] - p2['pos'])
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            for aspect_name, params in ASPECTS.items():
                if abs(angle_diff - params['angle']) < params['orb']:
                    line = f"- {prefix1}{p1_name}と{prefix2}{p2_name}が{aspect_name}"
                    aspect_list.append(line)
                    break
    if not aspect_list:
        return f"### {title}\n- 注目すべきタイトなアスペクトはありません。"
    return f"### {title}\n" + "\n".join(aspect_list)

def detect_lunation_and_eclipse(geo_points):
    sun_pos = geo_points["太陽"]['pos']
    moon_pos = geo_points["月"]['pos']
    node_pos = geo_points["ドラゴンヘッド"]['pos']
    sun_moon_diff = abs(sun_pos - moon_pos)
    if sun_moon_diff > 180:
        sun_moon_diff = 360 - sun_moon_diff
    event = None
    if sun_moon_diff < 3.0:
        event = "新月"
        sun_node_dist = abs(sun_pos - node_pos)
        if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
        if sun_node_dist < 15:
            event = "日食（新月）"
    elif abs(sun_moon_diff - 180) < 3.0:
        event = "満月"
        sun_node_dist = abs(sun_pos - node_pos)
        if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
        if sun_node_dist < 12:
            event = "月食（満月）"
    if event:
        return f"### 今日の天文イベント\n- 本日は**{event}**です。特別なエネルギーが流れる日です。"
    return ""

# --- AI・メール送信関数 ---
def generate_report_with_gemini(astro_data):
    """Gemini APIを呼び出して鑑定レポートを生成する"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEYが設定されていません。")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # ▼▼▼【変更点】プロンプトを外部ファイルから読み込む ▼▼▼
    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f:
            prompt_template = f.read()
    except FileNotFoundError:
        error_message = "<h2>レポート生成エラー</h2><p>プロンプトファイル 'prompt.txt' が見つかりませんでした。</p>"
        print(error_message)
        return error_message

    # プレースホルダーを実際のデータで置き換える
    prompt = prompt_template.format(
        date=datetime.now(timezone(timedelta(hours=9))).strftime('%Y年%m月%d日'),
        astro_data=astro_data
    )
    # ▲▲▲ ここまでが変更点 ▲▲▲

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini APIの呼び出し中にエラーが発生しました: {e}")
        return f"<h2>レポート生成エラー</h2><p>AIによるレポート生成に失敗しました。詳細: {e}</p>"

def send_email_with_sendgrid(html_content):
    """SendGrid APIを使ってメールを送信する"""
    if not SENDGRID_API_KEY or not TO_EMAIL:
        raise ValueError("SENDGRID_API_KEYまたはTO_EMAILが設定されていません。")
    if not FROM_EMAIL or "@" not in FROM_EMAIL:
        raise ValueError("FROM_EMAILが正しく設定されていません。SendGridで認証したメールアドレスを指定してください。")
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=TO_EMAIL,
        subject=f"今日の星占い ({datetime.now(timezone(timedelta(hours=9))).strftime('%Y/%m/%d')})",
        html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"メール送信成功: Status Code {response.status_code}")
    except Exception as e:
        print(f"SendGridでのメール送信中にエラーが発生しました: {e}")

# --- メイン処理 ---
def main():
    """メインの処理を実行する"""
    print("占星術レポート生成プロセスを開始します...")
    print("日本のネイタルチャートを計算中...")
    jd_natal = get_julian_day(**JAPAN_NATAL_DATA)
    japan_natal_points = calculate_celestial_points(jd_natal)
    print("今日のトランジットチャートを計算中...")
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    jd_transit = get_julian_day(now_jst.year, now_jst.month, now_jst.day, now_jst.hour, now_jst.minute, now_jst.second, 9.0)
    transit_geo_points = calculate_celestial_points(jd_transit)
    transit_helio_points = calculate_celestial_points(jd_transit, is_helio=True)
    print("AIプロンプト用のデータを編集中...")
    astro_data_parts = []
    astro_data_parts.append(detect_lunation_and_eclipse(transit_geo_points))
    astro_data_parts.append(format_positions_for_ai("今日の天体位置（地心）", transit_geo_points))
    astro_data_parts.append(format_positions_for_ai("今日の天体位置（太陽心）", transit_helio_points))
    astro_data_parts.append(calculate_aspects_for_ai("今日の世界の主要アスペクト", transit_geo_points, transit_geo_points, "T.", "T."))
    astro_data_parts.append(calculate_aspects_for_ai("日本への影響", transit_geo_points, japan_natal_points, "今日の", "日本の"))
    final_astro_data = "\n\n".join(filter(None, astro_data_parts))
    print("--- 生成された占星術データ ---")
    print(final_astro_data)
    print("--------------------------")
    print("Gemini APIを呼び出してレポートを生成中...")
    report_html = generate_report_with_gemini(final_astro_data)
    print("レポートが生成されました。")
    print("SendGrid APIを呼び出してメールを送信中...")
    send_email_with_sendgrid(report_html)
    print("プロセスが正常に完了しました。")

if __name__ == "__main__":
    try:
        if not os.path.exists(EPHE_PATH):
            raise FileNotFoundError(f"天体暦フォルダ '{EPHE_PATH}' が見つかりません。スクリプトと同じ階層に配置してください。")
        main()
    except Exception as e:
        print(f"処理中にエラーが発生しました: {e}")
