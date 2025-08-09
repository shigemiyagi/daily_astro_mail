# -*- coding: utf-8 -*-
# 必要なライブラリをインポートします
import os
import swisseph as swe  # 西洋占星術の計算を行うライブラリ
from datetime import datetime, timezone, timedelta  # 日時を扱うためのライブラリ
import google.generativeai as genai  # AIモデル（Gemini）を使用するためのライブラリ
from sendgrid import SendGridAPIClient  # メール送信サービスSendGridを使用するためのライブラリ
from sendgrid.helpers.mail import Mail  # SendGridでメールを作成するためのクラス
import traceback # エラーの詳細情報を表示するためにインポート

# --- 基本設定 ---

# スクリプト自身の場所を基準にして、'ephe'フォルダへの絶対パスを構築します。
# これにより、どこからスクリプトを実行してもパスが正しく解決されます。
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(SCRIPT_DIR, 'ephe')
swe.set_ephe_path(EPHE_PATH)

# 環境変数からAPIキーやメールアドレスを取得します。
# これにより、コード内に直接秘密情報を書き込むのを防ぎます。
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
TO_EMAIL = os.getenv('TO_EMAIL')
# SendGridで認証済みの送信元メールアドレスを指定します。
FROM_EMAIL = "shigemiyagi@gmail.com"

# --- 占星術関連の定数 ---

# 12星座の名前を定義します。計算結果の度数を星座名に変換する際に使用します。
SIGN_NAMES = ["牡羊座", "牡牛座", "双子座", "蟹座", "獅子座", "乙女座", "天秤座", "蠍座", "射手座", "山羊座", "水瓶座", "魚座"]
# 1つの星座が持つ度数（30度）を定義します。
DEGREES_PER_SIGN = 30

# 計算対象の天体・感受点を定義します。
GEO_CELESTIAL_BODIES = {
    "太陽": swe.SUN, "月": swe.MOON, "水星": swe.MERCURY, "金星": swe.VENUS,
    "火星": swe.MARS, "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS,
    "海王星": swe.NEPTUNE, "冥王星": swe.PLUTO,
    "ドラゴンヘッド": swe.MEAN_NODE,
    "リリス": swe.MEAN_APOG,
    "キロン": swe.CHIRON
}

# 太陽中心（ヘリオセントリック）で計算する天体
HELIO_CELESTIAL_BODIES = {
    "地球": swe.EARTH, "水星": swe.MERCURY, "金星": swe.VENUS, "火星": swe.MARS,
    "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS, "海王星": swe.NEPTUNE,
    "冥王星": swe.PLUTO
}

# アスペクト定義
ASPECTS = {
    "コンジャンクション (0度)": {"angle": 0, "orb": 8},
    "オポジション (180度)": {"angle": 180, "orb": 8},
    "トライン (120度)": {"angle": 120, "orb": 8},
    "スクエア (90度)": {"angle": 90, "orb": 6},
    "セクスタイル (60度)": {"angle": 60, "orb": 4},
}

# あなたの出生情報
PERSONAL_NATAL_DATA = {
    "year": 1976, "month": 12, "day": 25,
    "hour": 16, "minute": 25, "second": 0,
    "tz": 9.0,
    "lon": 127.8085, "lat": 26.3348,
    "house_system": b'P'
}


def get_julian_day(year, month, day, hour, minute, second, tz):
    """指定された日時（タイムゾーン対応）からユリウス日を計算する"""
    dt_local = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=tz)))
    dt_utc = dt_local.astimezone(timezone.utc)
    return swe.utc_to_jd(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, dt_utc.second, 1)[0]

def calculate_celestial_points(jd_ut, is_helio=False):
    """指定されたユリウス日から、各天体の位置（黄経）と速度を計算する"""
    points = {}
    # ▼▼▼【エラー修正】▼▼▼
    # 成功している参照コードに基づき、計算フラグをFLG_SWIEPHに変更します。
    # これにより、外部の天体暦ファイルを明示的に使用するよう指示します。
    iflag = swe.FLG_SWIEPH | swe.FLG_SPEED
    # ▲▲▲ ここまでが修正点 ▲▲▲

    celestial_bodies = HELIO_CELESTIAL_BODIES if is_helio else GEO_CELESTIAL_BODIES
    if is_helio:
        iflag |= swe.FLG_HELCTR

    for name, p_id in celestial_bodies.items():
        res, err = swe.calc_ut(jd_ut, p_id, iflag)
        if err:
            print(f"Warning: {name}の計算でエラーが発生しました: {err}")
            continue
        points[name] = {'pos': res[0], 'speed': res[3]}

    if "ドラゴンヘッド" in points:
        head_pos = points["ドラゴンヘッド"]['pos']
        points["ドラゴンテイル"] = {'pos': (head_pos + 180) % 360, 'speed': points["ドラゴンヘッド"]['speed']}

    return points

def calculate_houses(jd_ut, lat, lon, house_system):
    """ハウスカスプを計算する。高緯度などでのエラーを考慮する"""
    # ▼▼▼【改善】▼▼▼
    # 成功している参照コードに基づき、ハウス計算にエラーハンドリングを追加します。
    try:
        cusps, ascmc = swe.houses(jd_ut, lat, lon, house_system)
        return cusps
    except swe.Error as e:
        print(f"Warning: ハウスが計算できませんでした（高緯度など）。詳細: {e}")
        return None # 計算失敗時はNoneを返す
    # ▲▲▲ ここまでが改善点 ▲▲▲

def format_positions_for_ai(title, points):
    """天体位置をAIが解釈しやすいテキスト形式に変換する"""
    if not points: return ""
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
    """ハウスをAIが解釈しやすいテキスト形式に変換する"""
    if houses is None: return "" # ハウス計算が失敗した場合は何もしない
    lines = [f"### {title}"]
    for i in range(1, 13):
        pos = houses[i]
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        lines.append(f"- 第{i}ハウス: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def calculate_aspects_for_ai(title, points1, points2, prefix1="", prefix2=""):
    """アスペクトを計算し、AI用にフォーマットする"""
    if not points1 or not points2: return ""
    aspect_list = []
    p1_items, p2_items = list(points1.items()), list(points2.items())
    for i in range(len(p1_items)):
        for j in range(len(p2_items)):
            p1_name, p1_data = p1_items[i]
            p2_name, p2_data = p2_items[j]

            if points1 is points2 and i >= j:
                continue

            angle_diff = abs(p1_data['pos'] - p2_data['pos'])
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
    if not geo_points or "太陽" not in geo_points or "月" not in geo_points:
        return "### 今日の月齢\n- 月齢の計算に失敗しました。"

    sun_pos = geo_points["太陽"]['pos']
    moon_pos = geo_points["月"]['pos']
    moon_age_angle = (moon_pos - sun_pos + 360) % 360
    moon_age = moon_age_angle / 360 * 29.53
    result_text = f"### 今日の月齢\n- 本日の月齢は約{moon_age:.1f}です。"

    event = None
    sun_node_dist = float('inf')
    if "ドラゴンヘッド" in geo_points:
        node_pos = geo_points["ドラゴンヘッド"]['pos']
        sun_node_dist = abs(sun_pos - node_pos)
        if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist

    if moon_age_angle < 5 or moon_age_angle > 355:
        event = "日食（新月）" if sun_node_dist < 15 else "新月"
    elif abs(moon_age_angle - 180) < 5:
        event = "月食（満月）" if sun_node_dist < 12 else "満月"

    if event:
        result_text += f"\n- 本日は「{event}」です。特別なエネルギーが流れる日です。"
    return result_text

def generate_report_with_gemini(astro_data):
    """Gemini APIを呼び出してレポートを生成する"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    with open('prompt.txt', 'r', encoding='utf-8') as f:
        prompt_template = f.read()
    prompt = prompt_template.format(
        date=datetime.now(timezone(timedelta(hours=9))).strftime('%Y年%m月%d日'),
        astro_data=astro_data
    )
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini APIの呼び出し中にエラーが発生しました: {e}")
        raise

def send_email_with_sendgrid(html_content):
    """SendGrid APIを使ってHTMLメールを送信する"""
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=TO_EMAIL,
        subject=f"今日の星占い ({datetime.now(timezone(timedelta(hours=9))).strftime('%Y/%m/%d')})",
        html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"メール送信成功: Status Code {response.status_code}")
        if response.status_code >= 300:
             print(f"メール送信エラー: Body: {response.body}")
             raise RuntimeError(f"SendGridからの応答エラー (Status: {response.status_code})")
    except Exception as e:
        print(f"SendGridでのメール送信中にエラーが発生しました: {e}")
        raise

def main():
    """プログラムのメイン処理"""
    print("占星術レポート生成プロセスを開始します...")

    # 1. ネイタルチャート計算
    print("あなたのネイタルチャートを計算中...")
    jd_natal = get_julian_day(**{k: v for k, v in PERSONAL_NATAL_DATA.items() if k not in ['lon', 'lat', 'house_system']})
    natal_points = calculate_celestial_points(jd_natal)
    natal_houses = calculate_houses(jd_natal, PERSONAL_NATAL_DATA["lat"], PERSONAL_NATAL_DATA["lon"], PERSONAL_NATAL_DATA["house_system"])

    # 2. トランジットチャート計算
    print("今日のトランジットチャートを計算中...")
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    jd_transit = get_julian_day(now_jst.year, now_jst.month, now_jst.day, now_jst.hour, now_jst.minute, now_jst.second, 9.0)
    transit_geo_points = calculate_celestial_points(jd_transit)
    transit_helio_points = calculate_celestial_points(jd_transit, is_helio=True)

    if not natal_points or not transit_geo_points:
        raise RuntimeError("致命的なエラー: 天体計算に失敗しました。")

    # 3. AI用データ編集
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

    # 4. レポート生成とメール送信
    print("Gemini APIを呼び出してレポートを生成中...")
    report_html = generate_report_with_gemini(final_astro_data)
    print("レポートが生成されました。")

    print("SendGrid APIを呼び出してメールを送信中...")
    send_email_with_sendgrid(report_html)
    print("プロセスが正常に完了しました。")

if __name__ == "__main__":
    try:
        # --- 1. 起動前チェック ---
        print("設定ファイルのチェックを開始します...")
        # ▼▼▼【改善】▼▼▼
        # 参照している天体暦フォルダのフルパスを表示して、デバッグしやすくします。
        print(f"天体暦フォルダのパス: {EPHE_PATH}")
        if not os.path.exists(EPHE_PATH):
            raise FileNotFoundError(f"設定エラー: 天体暦フォルダ '{EPHE_PATH}' が見つかりません。")
        # ▲▲▲ ここまでが改善点 ▲▲▲

        if not os.path.exists('prompt.txt'):
            raise FileNotFoundError("設定エラー: プロンプトファイル 'prompt.txt' が見つかりませんでした。")
        
        required_vars = ['GEMINI_API_KEY', 'SENDGRID_API_KEY', 'TO_EMAIL']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"設定エラー: 以下の環境変数が設定されていません: {', '.join(missing_vars)}")
        
        if not FROM_EMAIL or "@" not in FROM_EMAIL:
            raise ValueError("設定エラー: 'FROM_EMAIL'が正しく設定されていません。")
        print(f"注意: 送信元メールアドレス '{FROM_EMAIL}' はSendGridで認証済みである必要があります。")
        
        print("設定ファイルのチェックが完了しました。")
        print("-" * 20)

        # --- 2. メイン処理の実行 ---
        main()

    except (FileNotFoundError, ValueError) as e:
        print(f"\n[エラー] {e}")
        print("設定を確認してから再度実行してください。")
    except Exception as e:
        print(f"\n[予期せぬエラーが発生しました]")
        traceback.print_exc()
    finally:
        print("-" * 20)
        print("swissephのリソースを解放します。")
        swe.close()
