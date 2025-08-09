# -*- coding: utf-8 -*-
import os
import swisseph as swe
from datetime import datetime, timezone, timedelta
import google.generativeai as genai
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# --- 基本設定 ---
# 天体暦(ephemeris)ファイルが格納されているフォルダのパス
EPHE_PATH = 'ephe'
swe.set_ephe_path(EPHE_PATH)

# 環境変数からAPIキーなどを取得
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
TO_EMAIL = os.getenv('TO_EMAIL')
# SendGridで認証済みの送信元メールアドレス
FROM_EMAIL = "shigemiyagi@gmail.com"

# --- 占星術関連の定数 ---
SIGN_NAMES = ["牡羊座", "牡牛座", "双子座", "蟹座", "獅子座", "乙女座", "天秤座", "蠍座", "射手座", "山羊座", "水瓶座", "魚座"]
DEGREES_PER_SIGN = 30

# 計算対象の天体・感受点リスト（地心占星術用）
GEO_CELESTIAL_BODIES = {
    "太陽": swe.SUN, "月": swe.MOON, "水星": swe.MERCURY, "金星": swe.VENUS,
    "火星": swe.MARS, "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS,
    "海王星": swe.NEPTUNE, "冥王星": swe.PLUTO,
    "ドラゴンヘッド": swe.MEAN_NODE,
    "リリス": swe.MEAN_APOG,
    "キロン": swe.CHIRON
}

# 参考情報として太陽心占星術の天体も定義
HELIO_CELESTIAL_BODIES = {
    "地球": swe.EARTH, "水星": swe.MERCURY, "金星": swe.VENUS, "火星": swe.MARS,
    "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS, "海王星": swe.NEPTUNE,
    "冥王星": swe.PLUTO
}

# 計算対象のアスペクトとオーブ（許容度数）
ASPECTS = {
    "コンジャンクション (0度)": {"angle": 0, "orb": 8},
    "オポジション (180度)": {"angle": 180, "orb": 8},
    "トライン (120度)": {"angle": 120, "orb": 8},
    "スクエア (90度)": {"angle": 90, "orb": 6},
    "セクスタイル (60度)": {"angle": 60, "orb": 4},
}

# 指定された出生情報
PERSONAL_NATAL_DATA = {
    "year": 1976,
    "month": 12,
    "day": 25,
    "hour": 16,
    "minute": 25,
    "second": 0,
    "tz": 9.0,
    "lon": 127.8085,
    "lat": 26.3348,
    "house_system": b'P'
}


def get_julian_day(year, month, day, hour, minute, second, tz):
    """指定された日時（タイムゾーン対応）からユリウス日を計算する"""
    dt_local = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=tz)))
    dt_utc = dt_local.astimezone(timezone.utc)
    return swe.utc_to_jd(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, dt_utc.second, 1)[0]

def calculate_celestial_points(jd_ut, is_helio=False):
    """天体の位置と速度を計算する。逆行判定も行う。"""
    points = {}
    # ▼▼▼【修正点】▼▼▼
    # Swiss Ephemerisファイルが見つからない場合に、組み込みのMoshier暦にフォールバックするよう設定
    # これにより、天体暦ファイルが不完全な場合でも計算が続行される
    iflag = swe.FLG_SWIEPH | swe.FLG_MOSEPH | swe.FLG_SPEED
    # ▲▲▲ ここまでが修正点 ▲▲▲
    celestial_bodies = HELIO_CELESTIAL_BODIES if is_helio else GEO_CELESTIAL_BODIES
    if is_helio:
        iflag |= swe.FLG_HELCTR

    for name, p_id in celestial_bodies.items():
        res, err = swe.calc_ut(jd_ut, p_id, iflag)
        if err:
            # エラーメッセージがbyte列の場合があるので、デコードを試みる
            try:
                err_msg = err.decode('utf-8')
            except (UnicodeDecodeError, AttributeError):
                err_msg = str(err)
            print(f"Warning: {name}の計算でエラー: {err_msg}")
            continue
        points[name] = {'pos': res[0], 'speed': res[3]}

    # ドラゴンテイルを計算
    if "ドラゴンヘッド" in points:
        head_pos = points["ドラゴンヘッド"]['pos']
        tail_pos = (head_pos + 180) % 360
        head_speed = points["ドラゴンヘッド"]['speed']
        points["ドラゴンテイル"] = {'pos': tail_pos, 'speed': head_speed}

    return points

def calculate_houses(jd_ut, lat, lon, house_system):
    """ハウスカスプを計算する"""
    cusps, ascmc = swe.houses(jd_ut, lat, lon, house_system)
    return cusps

def format_positions_for_ai(title, points):
    """天体位置をAIプロンプト用にフォーマットする"""
    lines = [f"### {title}"]
    for name, data in points.items():
        pos = data['pos']
        speed = data.get('speed', 1)
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        retrograde_marker = "(R)" if speed < 0 else ""
        lines.append(f"- {name}{retrograde_marker}: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def format_houses_for_ai(title, houses):
    """ハウス情報をAIプロンプト用にフォーマットする"""
    lines = [f"### {title}"]
    for i in range(1, 13):
      pos = houses[i]
      sign_index = int(pos / DEGREES_PER_SIGN)
      degree = pos % DEGREES_PER_SIGN
      lines.append(f"- 第{i}ハウス: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def calculate_aspects_for_ai(title, points1, points2, prefix1="", prefix2=""):
    """アスペクトを計算し、AI用にフォーマットする"""
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

def get_moon_age_and_event(geo_points):
    """月齢と、新月/満月/食のイベントを検出する"""
    if "太陽" not in geo_points or "月" not in geo_points:
        return "### 今日の月齢\n- 月齢の計算に失敗しました。"

    sun_pos = geo_points["太陽"]['pos']
    moon_pos = geo_points["月"]['pos']
    
    moon_age_angle = (moon_pos - sun_pos + 360) % 360
    moon_age = moon_age_angle / 360 * 29.53
    result_text = f"### 今日の月齢\n- 本日の月齢は約 **{moon_age:.1f}** です。"

    event = None
    if moon_age_angle < 5 or moon_age_angle > 355:
        event = "新月"
        if "ドラゴンヘッド" in geo_points:
            node_pos = geo_points["ドラゴンヘッド"]['pos']
            sun_node_dist = abs(sun_pos - node_pos)
            if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
            if sun_node_dist < 15:
                event = "日食（新月）"
    elif abs(moon_age_angle - 180) < 5:
        event = "満月"
        if "ドラゴンヘッド" in geo_points:
            node_pos = geo_points["ドラゴンヘッド"]['pos']
            sun_node_dist = abs(sun_pos - node_pos)
            if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
            if sun_node_dist < 12:
                event = "月食（満月）"

    if event:
        result_text += f"\n- 本日は**{event}**です。特別なエネルギーが流れる日です。"

    return result_text

def generate_report_with_gemini(astro_data):
    """Gemini APIを呼び出して鑑定レポートを生成する"""
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEYが設定されていません。")

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    try:
        with open('prompt.txt', 'r', encoding='utf-8') as f:
            prompt_template = f.read()
    except FileNotFoundError:
        return "<h2>レポート生成エラー</h2><p>プロンプトファイル 'prompt.txt' が見つかりませんでした。</p>"

    prompt = prompt_template.format(
        date=datetime.now(timezone(timedelta(hours=9))).strftime('%Y年%m月%d日'),
        astro_data=astro_data
    )
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini APIの呼び出し中にエラーが発生しました: {e}")
        return f"<h2>レポート生成エラー</h2><p>AIによるレポート生成に失敗しました。</p>"

def send_email_with_sendgrid(html_content):
    """SendGrid APIを使ってメールを送信する"""
    if not SENDGRID_API_KEY or not TO_EMAIL:
        raise ValueError("SENDGRID_API_KEYまたはTO_EMAILが設定されていません。")
    if not FROM_EMAIL or "@" not in FROM_EMAIL:
        raise ValueError("FROM_EMAILが正しく設定されていません。")
        
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

def main():
    """メインの処理を実行する"""
    print("占星術レポート生成プロセスを開始します...")

    # --- 1. ネイタルチャートの計算 ---
    print("あなたのネイタルチャートを計算中...")
    jd_natal = get_julian_day(
        PERSONAL_NATAL_DATA["year"],
        PERSONAL_NATAL_DATA["month"],
        PERSONAL_NATAL_DATA["day"],
        PERSONAL_NATAL_DATA["hour"],
        PERSONAL_NATAL_DATA["minute"],
        PERSONAL_NATAL_DATA["second"],
        PERSONAL_NATAL_DATA["tz"]
    )
    natal_points = calculate_celestial_points(jd_natal)
    natal_houses = calculate_houses(jd_natal, PERSONAL_NATAL_DATA["lat"], PERSONAL_NATAL_DATA["lon"], PERSONAL_NATAL_DATA["house_system"])

    # --- 2. 今日のトランジットチャートの計算 ---
    print("今日のトランジットチャートを計算中...")
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    jd_transit = get_julian_day(now_jst.year, now_jst.month, now_jst.day, now_jst.hour, now_jst.minute, now_jst.second, 9.0)
    transit_geo_points = calculate_celestial_points(jd_transit)
    transit_helio_points = calculate_celestial_points(jd_transit, is_helio=True)
        
    # ▼▼▼【修正点】▼▼▼
    # 天体計算が完全に失敗した場合の最終チェック
    if not natal_points or not transit_geo_points:
        print("\n致命的なエラー: 天体計算に失敗しました。")
        print("天体暦ファイルが'ephe'フォルダに正しく配置されているか、または破損していないか確認してください。")
        return # プログラムを終了
    # ▲▲▲ ここまでが修正点 ▲▲▲

    # --- 3. AIプロンプト用のデータ編集 ---
    print("AIプロンプト用のデータを編集中...")
    astro_data_parts = [
        get_moon_age_and_event(transit_geo_points),
        format_positions_for_ai("あなたのネイタル天体位置", natal_points),
        format_houses_for_ai("あなたのネイタルハウス", natal_houses),
        format_positions_for_ai("今日の天体位置（地心）", transit_geo_points),
        format_positions_for_ai("今日の天体位置（太陽心）", transit_helio_points),
        calculate_aspects_for_ai("あなたのネイタルアスペクト", natal_points, natal_points, "N.", "N."),
        calculate_aspects_for_ai("今日の空模様（トランジットアスペクト）", transit_geo_points, transit_geo_points, "T.", "T."),
        calculate_aspects_for_ai("あなたへの影響（トランジット/ネイタルアスペクト）", transit_geo_points, natal_points, "今日の", "あなたの")
    ]

    final_astro_data = "\n\n".join(filter(None, astro_data_parts))
    print("\n--- AIに送信する占星術データ ---\n")
    print(final_astro_data)
    print("\n--------------------------------\n")

    # --- 4. レポート生成とメール送信 ---
    print("Gemini APIを呼び出してレポートを生成中...")
    report_html = generate_report_with_gemini(final_astro_data)
    print("レポートが生成されました。")

    print("SendGrid APIを呼び出してメールを送信中...")
    send_email_with_sendgrid(report_html)
    print("プロセスが正常に完了しました。")

if __name__ == "__main__":
    try:
        # 起動時のファイルチェックは、より具体的なエラーメッセージをmain関数内で表示するため簡略化
        if not os.path.exists(EPHE_PATH):
            print(f"エラー: 天体暦フォルダ '{EPHE_PATH}' が見つかりません。")
        else:
            main()
    except Exception as e:
        print(f"処理中に予期せぬエラーが発生しました: {e}")
