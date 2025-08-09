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

# ▼▼▼【エラー修正】▼▼▼
# スクリプト自身の場所を基準にして、'ephe'フォルダへの絶対パスを構築します。
# これにより、どこからスクリプトを実行してもパスが正しく解決され、
# 天体暦ファイルの読み込みエラー(code 260)を防ぎます。
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EPHE_PATH = os.path.join(SCRIPT_DIR, 'ephe')
# ▲▲▲ ここまでが修正点 ▲▲▲
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
# キーが天体名、値がswissephライブラリで定められた天体番号です。
# GEO_CELESTIAL_BODIESは、地球から見た天体の位置（地心、ジオセントリック）を計算する際に使用します。
GEO_CELESTIAL_BODIES = {
    "太陽": swe.SUN, "月": swe.MOON, "水星": swe.MERCURY, "金星": swe.VENUS,
    "火星": swe.MARS, "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS,
    "海王星": swe.NEPTUNE, "冥王星": swe.PLUTO,
    "ドラゴンヘッド": swe.MEAN_NODE,  # 月の軌道と黄道が交差する点（平均位置）
    "リリス": swe.MEAN_APOG,      # 月の軌道上で地球から最も遠い点（平均位置）
    "キロン": swe.CHIRON        # 小惑星カイロン
}

# HELIO_CELESTIAL_BODIESは、太陽から見た天体の位置（太陽心、ヘリオセントリック）を計算する際に使用します。
# 参考情報として利用します。
HELIO_CELESTIAL_BODIES = {
    "地球": swe.EARTH, "水星": swe.MERCURY, "金星": swe.VENUS, "火星": swe.MARS,
    "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS, "海王星": swe.NEPTUNE,
    "冥王星": swe.PLUTO
}

# 計算対象のアスペクト（天体間の角度）とオーブ（許容度数）を定義します。
# 例えば、コンジャンクション（0度）は、オーブ8度以内であれば成立すると見なします。
ASPECTS = {
    "コンジャンクション (0度)": {"angle": 0, "orb": 8},
    "オポジション (180度)": {"angle": 180, "orb": 8},
    "トライン (120度)": {"angle": 120, "orb": 8},
    "スクエア (90度)": {"angle": 90, "orb": 6},
    "セクスタイル (60度)": {"angle": 60, "orb": 4},
}

# あなたの出生情報をハードコーディングします。
PERSONAL_NATAL_DATA = {
    "year": 1976,
    "month": 12,
    "day": 25,
    "hour": 16,
    "minute": 25,
    "second": 0,
    "tz": 9.0,        # 日本標準時 (JST)
    "lon": 127.8085,    # 沖縄県沖縄市の経度
    "lat": 26.3348,     # 沖縄県沖縄市の緯度
    "house_system": b'P' # ハウスシステム (P: プラシーダス)
}


def get_julian_day(year, month, day, hour, minute, second, tz):
    """
    指定された日時（タイムゾーン対応）からユリウス日を計算します。
    ホロスコープ計算には、世界共通の時刻基準であるユリウス日が必要です。
    """
    # タイムゾーン付きのdatetimeオブジェクトを作成
    dt_local = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=tz)))
    # UTC（協定世界時）に変換
    dt_utc = dt_local.astimezone(timezone.utc)
    # UTC日時をユリウス日に変換
    return swe.utc_to_jd(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, dt_utc.second, 1)[0]

def calculate_celestial_points(jd_ut, is_helio=False):
    """
    指定されたユリウス日から、各天体の位置（黄経）と速度を計算します。
    """
    points = {}
    # 計算方法を指定するフラグです。
    # swe.FLG_MOSEPH: 外部の天体暦ファイル(Swiss Ephemeris)が見つからない場合、
    #                 ライブラリ内蔵の計算方法(Moshier)を自動的に使用します。
    #                 これにより、ファイル不足によるエラーを回避します。
    # swe.FLG_SPEED: 天体の「速度」も計算します。これにより逆行判定が可能になります。
    iflag = swe.FLG_MOSEPH | swe.FLG_SPEED

    # 計算対象の天体リストを選択します（地心か太陽心か）。
    celestial_bodies = HELIO_CELESTIAL_BODIES if is_helio else GEO_CELESTIAL_BODIES
    if is_helio:
        iflag |= swe.FLG_HELCTR  # 太陽心で計算する場合のフラグを追加

    for name, p_id in celestial_bodies.items():
        # ユリウス日、天体番号、計算フラグを渡して天体情報を計算
        res, err = swe.calc_ut(jd_ut, p_id, iflag)
        if err:
            # 計算中にエラーが発生した場合は、警告を表示して処理を続行
            print(f"Warning: {name}の計算でエラーが発生しました: {err}")
            continue
        # 計算結果から、黄経(res[0])と速度(res[3])を辞書に格納
        points[name] = {'pos': res[0], 'speed': res[3]}

    # ドラゴンテイルの位置を計算します（ドラゴンヘッドのちょうど180度反対側）。
    if "ドラゴンヘッド" in points:
        head_pos = points["ドラゴンヘッド"]['pos']
        tail_pos = (head_pos + 180) % 360
        head_speed = points["ドラゴンヘッド"]['speed']
        points["ドラゴンテイル"] = {'pos': tail_pos, 'speed': head_speed}

    return points

def calculate_houses(jd_ut, lat, lon, house_system):
    """
    ハウスカスプ（ハウスの始まりの位置）を計算します。
    ハウスは、天体のエネルギーが人生のどの分野で発揮されるかを示します。
    """
    # ユリウス日、緯度、経度、ハウスシステムを渡してハウス情報を計算
    cusps, ascmc = swe.houses(jd_ut, lat, lon, house_system)
    return cusps

def format_positions_for_ai(title, points):
    """天体位置の計算結果を、AIが解釈しやすいテキスト形式に変換します。"""
    lines = [f"### {title}"]
    for name, data in points.items():
        pos = data['pos']
        speed = data.get('speed', 1)
        # 度数を「星座名 + 度数」の形式に変換
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        # 速度がマイナスの場合、逆行していると判断し「(R)」マークを付けます。
        retrograde_marker = "(R)" if speed < 0 else ""
        lines.append(f"- {name}{retrograde_marker}: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def format_houses_for_ai(title, houses):
    """ハウスの計算結果を、AIが解釈しやすいテキスト形式に変換します。"""
    lines = [f"### {title}"]
    # houses配列の添字1から12が、第1ハウスから第12ハウスに対応します。
    for i in range(1, 13):
        pos = houses[i]
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        lines.append(f"- 第{i}ハウス: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)

def calculate_aspects_for_ai(title, points1, points2, prefix1="", prefix2=""):
    """2つの天体リスト間のアスペクトを計算し、AI用にフォーマットします。"""
    aspect_list = []
    p1_names, p2_names = list(points1.keys()), list(points2.keys())
    for i in range(len(p1_names)):
        for j in range(len(p2_names)):
            # 同じ天体リスト同士を比較する場合、重複を避けます (例: 太陽-月は計算し、月-太陽はスキップ)
            if points1 is points2 and i >= j:
                continue
            
            p1_name, p2_name = p1_names[i], p2_names[j]
            p1, p2 = points1[p1_name], points2[p2_name]
            
            # 2天体間の角度差を計算 (0-180度の範囲に正規化)
            angle_diff = abs(p1['pos'] - p2['pos'])
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
                
            # 定義したアスペクトに合致するかチェック
            for aspect_name, params in ASPECTS.items():
                if abs(angle_diff - params['angle']) < params['orb']:
                    line = f"- {prefix1}{p1_name}と{prefix2}{p2_name}が{aspect_name}"
                    aspect_list.append(line)
                    break  # 最初に見つかったアスペクトで判定終了
                    
    if not aspect_list:
        return f"### {title}\n- 注目すべきタイトなアスペクトはありません。"
    return f"### {title}\n" + "\n".join(aspect_list)

def get_moon_age_and_event(geo_points):
    """月齢と、新月/満月/食のイベントを検出します。"""
    if "太陽" not in geo_points or "月" not in geo_points:
        return "### 今日の月齢\n- 月齢の計算に失敗しました。"

    sun_pos = geo_points["太陽"]['pos']
    moon_pos = geo_points["月"]['pos']
    
    # 月齢を計算 (太陽と月の離角から算出。1周29.53日とします)
    moon_age_angle = (moon_pos - sun_pos + 360) % 360
    moon_age = moon_age_angle / 360 * 29.53
    result_text = f"### 今日の月齢\n- 本日の月齢は約 {moon_age:.1f} です。"

    # 新月・満月・食のイベントを判定
    event = None
    if moon_age_angle < 5 or moon_age_angle > 355: # 新月付近
        event = "新月"
        if "ドラゴンヘッド" in geo_points:
            node_pos = geo_points["ドラゴンヘッド"]['pos']
            sun_node_dist = abs(sun_pos - node_pos)
            if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
            if sun_node_dist < 15:  # オーブ15度以内なら日食の可能性
                event = "日食（新月）"
    elif abs(moon_age_angle - 180) < 5: # 満月付近
        event = "満月"
        if "ドラゴンヘッド" in geo_points:
            node_pos = geo_points["ドラゴンヘッド"]['pos']
            sun_node_dist = abs(sun_pos - node_pos)
            if sun_node_dist > 180: sun_node_dist = 360 - sun_node_dist
            if sun_node_dist < 12:  # オーブ12度以内なら月食の可能性
                event = "月食（満月）"

    if event:
        result_text += f"\n- 本日は「{event}」です。特別なエネルギーが流れる日です。"

    return result_text

def generate_report_with_gemini(astro_data):
    """Gemini APIを呼び出して、占星術データに基づいたレポートを生成します。"""
    # APIキーのチェックは起動時に行うため、ここでは不要
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    # prompt.txtの存在チェックも起動時に行う
    with open('prompt.txt', 'r', encoding='utf-8') as f:
        prompt_template = f.read()

    # プロンプトのテンプレートに、今日の日付と計算した占星術データを埋め込みます。
    prompt = prompt_template.format(
        date=datetime.now(timezone(timedelta(hours=9))).strftime('%Y年%m月%d日'),
        astro_data=astro_data
    )
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Gemini APIの呼び出し中にエラーが発生しました: {e}")
        # エラーが発生した場合、呼び出し元でキャッチされるように例外を再発生させる
        raise

def send_email_with_sendgrid(html_content):
    """SendGrid APIを使って、生成されたレポートをHTMLメールとして送信します。"""
    # APIキーなどのチェックは起動時に行う
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=TO_EMAIL,
        subject=f"今日の星占い ({datetime.now(timezone(timedelta(hours=9))).strftime('%Y/%m/%d')})",
        html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        print(f"メール送信成功: Status Code {response.status_code}")
        # 2xx以外のステータスコードはエラーとして扱う
        if response.status_code < 200 or response.status_code >= 300:
             print(f"メール送信エラー: Body: {response.body}")
             raise RuntimeError(f"SendGridからの応答エラー (Status: {response.status_code})")
    except Exception as e:
        print(f"SendGridでのメール送信中にエラーが発生しました: {e}")
        raise

def main():
    """
    プログラムのメイン処理。
    ホロスコープ計算からメール送信までの一連の流れを制御します。
    """
    print("占星術レポート生成プロセスを開始します...")

    # 1. あなたのネイタルチャート（出生図）を計算
    print("あなたのネイタルチャートを計算中...")
    jd_natal = get_julian_day(
        year=PERSONAL_NATAL_DATA["year"],
        month=PERSONAL_NATAL_DATA["month"],
        day=PERSONAL_NATAL_DATA["day"],
        hour=PERSONAL_NATAL_DATA["hour"],
        minute=PERSONAL_NATAL_DATA["minute"],
        second=PERSONAL_NATAL_DATA["second"],
        tz=PERSONAL_NATAL_DATA["tz"]
    )
    natal_points = calculate_celestial_points(jd_natal)
    natal_houses = calculate_houses(jd_natal, PERSONAL_NATAL_DATA["lat"], PERSONAL_NATAL_DATA["lon"], PERSONAL_NATAL_DATA["house_system"])

    # 2. 今日のトランジットチャート（現在の星の配置）を計算
    print("今日のトランジットチャートを計算中...")
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    jd_transit = get_julian_day(now_jst.year, now_jst.month, now_jst.day, now_jst.hour, now_jst.minute, now_jst.second, 9.0)
    transit_geo_points = calculate_celestial_points(jd_transit)
    transit_helio_points = calculate_celestial_points(jd_transit, is_helio=True)
        
    # 天体計算が完全に失敗した場合の最終チェック
    if not natal_points or not transit_geo_points:
        # このエラーは致命的なので、例外を発生させて終了させる
        raise RuntimeError("致命的なエラー: 天体計算に失敗しました。swissephライブラリか天体暦ファイルを確認してください。")

    # 3. AIに渡すための占星術データを編集
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

# このスクリプトが直接実行された場合に、main()関数を呼び出します。
if __name__ == "__main__":
    try:
        # --- 1. 起動前チェック ---
        print("設定ファイルのチェックを開始します...")
        # 天体暦フォルダ
        if not os.path.exists(EPHE_PATH):
            raise FileNotFoundError(f"設定エラー: 天体暦フォルダ '{EPHE_PATH}' が見つかりません。")
        
        # プロンプトファイル
        if not os.path.exists('prompt.txt'):
            raise FileNotFoundError("設定エラー: プロンプトファイル 'prompt.txt' が見つかりませんでした。")
        
        # 環境変数
        required_vars = ['GEMINI_API_KEY', 'SENDGRID_API_KEY', 'TO_EMAIL']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(f"設定エラー: 以下の環境変数が設定されていません: {', '.join(missing_vars)}")
        
        # 送信元メールアドレスの形式チェックと注意喚起
        if not FROM_EMAIL or "@" not in FROM_EMAIL:
            raise ValueError("設定エラー: 'FROM_EMAIL'が正しく設定されていません。")
        print(f"注意: 送信元メールアドレス '{FROM_EMAIL}' はSendGridで認証済みである必要があります。")
        
        print("設定ファイルのチェックが完了しました。")
        print("-" * 20)

        # --- 2. メイン処理の実行 ---
        main()

    except (FileNotFoundError, ValueError) as e:
        # 設定関連のエラーをまとめてキャッチして表示
        print(f"\n[エラー] {e}")
        print("設定を確認してから再度実行してください。")

    except Exception as e:
        # 上記以外の予期せぬエラーをキャッチ
        print(f"\n[予期せぬエラーが発生しました]")
        # tracebackを使って、エラーの詳細（どのファイルの何行目で発生したか）を表示
        traceback.print_exc()

    finally:
        # プログラムが正常終了しても、エラーで終了しても、必ず最後に実行される
        # swissephのリソースを解放します。
        print("-" * 20)
        print("swissephのリソースを解放します。")
        swe.close()
