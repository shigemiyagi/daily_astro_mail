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

# 計算対象の天体・感受点を定義します（占星術的重要度順に配置）。
GEO_CELESTIAL_BODIES = {
    "太陽": swe.SUN, 
    "月": swe.MOON, 
    "水星": swe.MERCURY, 
    "金星": swe.VENUS,
    "火星": swe.MARS, 
    "木星": swe.JUPITER, 
    "土星": swe.SATURN, 
    "天王星": swe.URANUS,
    "海王星": swe.NEPTUNE, 
    "冥王星": swe.PLUTO,
    "ドラゴンヘッド": swe.TRUE_NODE,  # 真のドラゴンヘッドを使用
    "キロン": swe.CHIRON,  # キロンをリリスより優先
    "リリス": swe.MEAN_APOG  # 平均リリスは最後
}

# 太陽中心（ヘリオセントリック）で計算する天体
HELIO_CELESTIAL_BODIES = {
    "地球": swe.EARTH, "水星": swe.MERCURY, "金星": swe.VENUS, "火星": swe.MARS,
    "木星": swe.JUPITER, "土星": swe.SATURN, "天王星": swe.URANUS, "海王星": swe.NEPTUNE,
    "冥王星": swe.PLUTO
}

# アスペクト定義（オーブを修正）
ASPECTS = {
    "コンジャンクション (0度)": {"angle": 0, "orb": 6},
    "オポジション (180度)": {"angle": 180, "orb": 6},
    "トライン (120度)": {"angle": 120, "orb": 5},
    "スクエア (90度)": {"angle": 90, "orb": 5},
    "セクスタイル (60度)": {"angle": 60, "orb": 4},
}

# あなたの出生情報
PERSONAL_NATAL_DATA = {
    "year": 1976, "month": 12, "day": 25,
    "hour": 16, "minute": 25, "second": 0,
    "tz": 9.0,
    "lon": 127.8085, "lat": 26.3348,
    "house_system": b'W'  # Whole Signハウス（Placidusより安定）
}


def setup_swiss_ephemeris():
    """Swiss Ephemerisの初期設定とテストを行う"""
    print(f"天体暦パスを設定中: {EPHE_PATH}")
    
    # パスを設定
    swe.set_ephe_path(EPHE_PATH)
    
    # テスト用の日付（現在の日付に近い値）
    test_jd = 2460676.0  # 2025年1月頃
    
    try:
        print(f"テスト計算実行中 (JD={test_jd})...")
        
        # 最もシンプルな太陽の計算でテスト（フラグなし）
        result = swe.calc_ut(test_jd, swe.SUN, swe.FLG_SWIEPH)
        print(f"calc_ut戻り値のタイプ: {type(result)}")
        print(f"calc_ut戻り値の長さ: {len(result) if hasattr(result, '__len__') else 'スカラー'}")
        print(f"calc_ut戻り値: {result}")
        
        # 戻り値の構造を調べる
        if isinstance(result, (tuple, list)) and len(result) >= 2:
            pos_data = result[0]
            err_data = result[1]
            print(f"位置データ: {type(pos_data)} = {pos_data}")
            print(f"エラーデータ: {type(err_data)} = {err_data}")
            
            if isinstance(pos_data, (tuple, list)) and len(pos_data) > 0:
                sun_pos = pos_data[0]
                print(f"テスト成功: 太陽位置 = {sun_pos:.2f}度")
                return True
            else:
                print(f"エラー: 位置データが無効 = {pos_data}")
                return False
        else:
            print(f"エラー: 予期しない戻り値構造 = {result}")
            return False
            
    except Exception as e:
        print(f"Swiss Ephemeris設定テスト失敗: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_julian_day(year, month, day, hour, minute, second, tz):
    """指定された日時（タイムゾーン対応）からユリウス日を計算する"""
    print(f"\n=== ユリウス日計算 ===")
    print(f"入力日時: {year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d} (UTC{tz:+.1f})")
    
    try:
        # タイムゾーン変換
        dt_local = datetime(year, month, day, hour, minute, second, tzinfo=timezone(timedelta(hours=tz)))
        dt_utc = dt_local.astimezone(timezone.utc)
        print(f"UTC変換後: {dt_utc}")
        
        # ユリウス日計算
        jd_result = swe.utc_to_jd(dt_utc.year, dt_utc.month, dt_utc.day, dt_utc.hour, dt_utc.minute, dt_utc.second, 1)
        print(f"utc_to_jd戻り値: {type(jd_result)} = {jd_result}")
        
        if isinstance(jd_result, (tuple, list)) and len(jd_result) > 0:
            jd_ut = jd_result[0]
        else:
            jd_ut = jd_result  # スカラーの場合
            
        print(f"ユリウス日: {jd_ut}")
        
        # 妥当性チェック
        if not isinstance(jd_ut, (int, float)):
            raise ValueError(f"ユリウス日が数値ではありません: {type(jd_ut)}")
            
        if jd_ut < 1000000 or jd_ut > 3000000:  # 大まかな範囲チェック
            print(f"警告: ユリウス日が予期しない範囲: {jd_ut}")
            # ただし処理は継続
        
        return jd_ut
        
    except Exception as e:
        print(f"ユリウス日計算エラー: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise


def calculate_celestial_points(jd_ut, is_helio=False):
    """指定されたユリウス日から、各天体の位置（黄経）と速度を計算する"""
    print(f"\n=== 天体計算開始 ===")
    print(f"ユリウス日: {jd_ut}")
    print(f"ヘリオセントリック: {is_helio}")
    
    points = {}
    
    # フラグ設定（速度計算を含む）
    if is_helio:
        iflag = swe.FLG_SWIEPH | swe.FLG_HELCTR | swe.FLG_SPEED
    else:
        iflag = swe.FLG_SWIEPH | swe.FLG_SPEED
    
    print(f"使用フラグ: {iflag}")

    celestial_bodies = HELIO_CELESTIAL_BODIES if is_helio else GEO_CELESTIAL_BODIES
    successful_calculations = 0
    total_calculations = len(celestial_bodies)

    for name, p_id in celestial_bodies.items():
        print(f"\n--- {name}の計算開始 (ID={p_id}) ---")
        
        try:
            # 計算実行
            result = swe.calc_ut(jd_ut, p_id, iflag)
            
            # 戻り値の基本チェック
            if not isinstance(result, (tuple, list)) or len(result) < 2:
                print(f"エラー: 戻り値の構造が無効: {result}")
                continue
            
            pos_data = result[0]
            status_code = result[1]  # これはエラーコードではなくステータスフラグ
            
            print(f"位置データ: {pos_data}")
            print(f"ステータスコード: {status_code}")
            
            # 位置データの妥当性チェック
            if not isinstance(pos_data, (tuple, list)) or len(pos_data) < 1:
                print(f"エラー: 位置データが無効")
                continue
            
            longitude = pos_data[0]
            speed = pos_data[3] if len(pos_data) > 3 else 1.0
            
            # データ型の妥当性チェック
            if not isinstance(longitude, (int, float)):
                print(f"エラー: 黄経が数値ではありません: {type(longitude)}")
                continue
            
            # 異常な値のチェック（ただし、計算結果として受け入れる）
            if longitude < -360 or longitude > 720:
                print(f"警告: 黄経が大きく範囲外: {longitude}")
            
            # 黄経を0-360度の範囲に正規化
            normalized_longitude = longitude % 360
            
            points[name] = {'pos': normalized_longitude, 'speed': speed}
            successful_calculations += 1
            print(f"成功: {normalized_longitude:.2f}度 (速度: {speed:.6f})")
            
        except Exception as e:
            print(f"例外発生: {type(e).__name__}: {e}")
            continue

    print(f"\n=== 計算結果 ===")
    print(f"成功: {successful_calculations}/{total_calculations}")
    
    # ドラゴンテイルの計算
    if "ドラゴンヘッド" in points:
        head_pos = points["ドラゴンヘッド"]['pos']
        tail_pos = (head_pos + 180) % 360
        points["ドラゴンテイル"] = {'pos': tail_pos, 'speed': points["ドラゴンヘッド"]['speed']}
        successful_calculations += 1
        print(f"ドラゴンテイル追加: {tail_pos:.2f}度")

    final_count = successful_calculations
    total_with_tail = total_calculations + (1 if not is_helio and 'ドラゴンヘッド' in GEO_CELESTIAL_BODIES else 0)
    print(f"最終結果: {final_count}/{total_with_tail}")
    
    return points


def calculate_houses(jd_ut, lat, lon, house_system):
    """ハウスカスプを計算する。高緯度などでのエラーを考慮する"""
    try:
        # housesの戻り値は (カスプのリスト, (ASC, MC, ...)) のタプル
        result = swe.houses(jd_ut, lat, lon, house_system)
        if not result or len(result) < 1:
            print("Warning: ハウス計算の結果が無効です")
            return None
        
        cusps = result[0]
        if not cusps or len(cusps) < 13:  # インデックス0-12まで必要
            print("Warning: ハウスカスプが不完全です")
            return None
        
        return cusps
    except Exception as e:
        print(f"Warning: ハウスが計算できませんでした（高緯度など）。詳細: {e}")
        return None


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
    # ハウスカスプは1-12まで。houses[0]は使わない。
    for i in range(1, 13):
        pos = houses[i]
        sign_index = int(pos / DEGREES_PER_SIGN)
        degree = pos % DEGREES_PER_SIGN
        lines.append(f"- 第{i}ハウス: {SIGN_NAMES[sign_index]} {degree:.2f}度")
    return "\n".join(lines)


def calculate_days_until_aspect_ends(jd_ut, transit_body_id, transit_pos, transit_speed, natal_pos, aspect_angle, orb):
    """アスペクトが規定オーブ外になるまでの日数を計算"""
    if abs(transit_speed) < 0.0001:  # 速度がほぼ0の場合は計算不能
        return None
    
    print(f"残り日数計算: 天体ID={transit_body_id}, 現在位置={transit_pos:.2f}, 速度={transit_speed:.6f}")
    
    # 現在の角度差
    current_angle_diff = abs((transit_pos - natal_pos + 180) % 360 - 180)
    if current_angle_diff > 180:
        current_angle_diff = 360 - current_angle_diff
    
    # アスペクト角度に対する現在のオーブ
    current_orb = abs(current_angle_diff - aspect_angle)
    print(f"現在のオーブ: {current_orb:.2f}度, 許容オーブ: {orb}度")
    
    try:
        # 1日後から最大30日後まで1日刻みでチェック
        for days_ahead in range(1, 31):
            future_jd = jd_ut + days_ahead
            
            # 未来の天体位置を計算
            try:
                result = swe.calc_ut(future_jd, transit_body_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
                if not isinstance(result, (tuple, list)) or len(result) < 2:
                    print(f"日{days_ahead}: calc_ut結果が無効")
                    continue
                    
                pos_data = result[0]
                if not isinstance(pos_data, (tuple, list)) or len(pos_data) < 1:
                    print(f"日{days_ahead}: 位置データが無効")
                    continue
                    
                future_pos = pos_data[0] % 360
                
                # 未来の角度差を計算
                future_angle_diff = abs((future_pos - natal_pos + 180) % 360 - 180)
                if future_angle_diff > 180:
                    future_angle_diff = 360 - future_angle_diff
                
                future_orb = abs(future_angle_diff - aspect_angle)
                
                # デバッグ出力（最初の3日分のみ）
                if days_ahead <= 3:
                    print(f"日{days_ahead}: 位置={future_pos:.2f}, オーブ={future_orb:.2f}")
                
                # オーブが規定値を超えた場合
                if future_orb > orb:
                    print(f"結果: {days_ahead}日後にオーブ外になる")
                    return days_ahead
                    
            except Exception as e:
                print(f"日{days_ahead}: 天体計算エラー - {e}")
                continue
        
        # 30日以内にオーブ外にならない場合
        print(f"結果: 30日以上継続")
        return None
        
    except Exception as e:
        print(f"残り日数計算の全般エラー: {e}")
        return None


def calculate_aspects_for_ai(title, points1, points2, prefix1="", prefix2="", jd_ut=None):
    """アスペクトを計算し、AI用にフォーマットする（残り日数も含む）"""
    if not points1 or not points2: return ""
    aspect_list = []
    p1_items, p2_items = list(points1.items()), list(points2.items())
    
    for i in range(len(p1_items)):
        for j in range(len(p2_items)):
            p1_name, p1_data = p1_items[i]
            p2_name, p2_data = p2_items[j]

            # 同じ天体リスト内で完全に同じ天体同士（同じインデックス）は除外
            # 異なるリスト間（トランジット-ネイタル）や、同じリスト内でも異なる天体は計算する
            if points1 is points2 and i == j:
                continue

            pos1, speed1 = p1_data['pos'], p1_data['speed']
            pos2, speed2 = p2_data['pos'], p2_data['speed']
            
            # 角度差を計算
            angle_diff = abs(pos1 - pos2)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff

            # 各アスペクトをチェック
            for aspect_name, params in ASPECTS.items():
                orb_diff = abs(angle_diff - params['angle'])
                if orb_diff <= params['orb']:
                    # Applying/Separatingの判定
                    applying_separating = ""
                    if points1 is not points2:  # トランジット-ネイタル間のみ判定
                        speed_diff = speed1 - speed2
                        if speed_diff > 0.001:  # 近づいている
                            applying_separating = " (A)"
                        elif speed_diff < -0.001:  # 離れている
                            applying_separating = " (S)"
                    
                    # 残り日数の計算（トランジット-ネイタルの場合のみ）
                    days_remaining = ""
                    if points1 is not points2 and jd_ut is not None:
                        # トランジット天体のIDを取得
                        transit_body_id = None
                        for body_name, body_id in GEO_CELESTIAL_BODIES.items():
                            if body_name == p1_name:
                                transit_body_id = body_id
                                break
                        
                        if transit_body_id is not None:
                            days_left = calculate_days_until_aspect_ends(
                                jd_ut, transit_body_id, pos1, speed1, pos2, params['angle'], params['orb']
                            )
                            if days_left is not None:
                                days_remaining = f" (残り{days_left}日)"
                            else:
                                days_remaining = " (30日以上)"
                    
                    orb_str = f"{orb_diff:.1f}度"
                    line = f"- {prefix1}{p1_name}と{prefix2}{p2_name}が{aspect_name} (オーブ: {orb_str}){applying_separating}{days_remaining}"
                    aspect_list.append((orb_diff, line))  # オーブでソート用
                    break  # 1つのアスペクトが見つかったら次へ
    
    # オーブの小さい順にソート
    aspect_list.sort(key=lambda x: x[0])
    
    if not aspect_list:
        return f"### {title}\n- 指定オーブ内のタイトなアスペクトはありません。"
    
    # ソートされた結果を返す
    sorted_lines = [line for _, line in aspect_list]
    return f"### {title}\n" + "\n".join(sorted_lines)


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
    model = genai.GenerativeModel('gemini-2.5-flash')
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

    # Swiss Ephemerisの設定とテスト
    if not setup_swiss_ephemeris():
        raise RuntimeError("Swiss Ephemerisの初期設定に失敗しました。天体暦ファイルを確認してください。")

    # 1. ネイタルチャート計算
    print("あなたのネイタルチャートを計算中...")
    # get_julian_dayに不要な引数を渡さないように辞書内包表記でフィルタリング
    jd_natal = get_julian_day(**{k: v for k, v in PERSONAL_NATAL_DATA.items() if k not in ['lon', 'lat', 'house_system']})
    natal_points = calculate_celestial_points(jd_natal)
    natal_houses = calculate_houses(jd_natal, PERSONAL_NATAL_DATA["lat"], PERSONAL_NATAL_DATA["lon"], PERSONAL_NATAL_DATA["house_system"])

    # 2. トランジットチャート計算
    print("今日のトランジットチャートを計算中...")
    now_jst = datetime.now(timezone(timedelta(hours=9)))
    jd_transit = get_julian_day(now_jst.year, now_jst.month, now_jst.day, now_jst.hour, now_jst.minute, now_jst.second, 9.0)
    transit_geo_points = calculate_celestial_points(jd_transit)
    transit_helio_points = calculate_celestial_points(jd_transit, is_helio=True)

    # 計算結果の妥当性チェック（より現実的な閾値に）
    min_required_points = 3  # 最低限必要な天体数を更に下げる
    if len(natal_points) < min_required_points:
        print(f"警告: ネイタル天体の計算成功数が少ないです: {len(natal_points)}")
        if len(natal_points) == 0:
            raise RuntimeError(f"致命的なエラー: ネイタル天体計算に全て失敗しました")
    
    if len(transit_geo_points) < min_required_points:
        print(f"警告: トランジット天体の計算成功数が少ないです: {len(transit_geo_points)}")
        if len(transit_geo_points) == 0:
            raise RuntimeError(f"致命的なエラー: トランジット天体計算に全て失敗しました")

    print(f"計算成功: ネイタル天体 {len(natal_points)}個, トランジット天体 {len(transit_geo_points)}個")

    # 3. AI用データ編集（アスペクト出力を制限、残り日数付き）
    print("AIプロンプト用のデータを編集中...")
    astro_data_parts = [
        get_moon_age_and_event(transit_geo_points),
        format_positions_for_ai("あなたのネイタル天体位置", natal_points),
        format_houses_for_ai("あなたのネイタルハウス", natal_houses),
        format_positions_for_ai("今日の天体位置（地心）", transit_geo_points),
        format_positions_for_ai("今日の天体位置（太陽心）", transit_helio_points),
        # ネイタルアスペクトは削除（要求により）
        # calculate_aspects_for_ai("あなたのネイタルアスペクト", natal_points, natal_points, "N.", "N."),
        calculate_aspects_for_ai("今日の空模様（トランジットアスペクト）", transit_geo_points, transit_geo_points, "T.", "T.", jd_transit),
        calculate_aspects_for_ai("あなたへの影響（トランジット/ネイタルアスペクト）", transit_geo_points, natal_points, "今日の", "あなたの", jd_transit)
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
        print(f"天体暦フォルダのパス: {EPHE_PATH}")
        if not os.path.exists(EPHE_PATH):
            raise FileNotFoundError(f"設定エラー: 天体暦フォルダ '{EPHE_PATH}' が見つかりません。")

        # 天体暦フォルダの中身を検査
        print("天体暦フォルダの内容を検査します...")
        try:
            files_in_ephe = os.listdir(EPHE_PATH)
            if not files_in_ephe:
                print("警告: 'ephe'フォルダは空です。天体暦ファイル（.se1）を配置してください。")
            else:
                print(f"天体暦フォルダ内のファイル数: {len(files_in_ephe)}")
                se1_files = [f for f in files_in_ephe if f.endswith('.se1')]
                print(f".se1ファイル数: {len(se1_files)}")
                
                # 代表的なファイル(冥王星)のサイズをチェック
                pluto_file_path = os.path.join(EPHE_PATH, 'sepl_18.se1')
                if os.path.exists(pluto_file_path):
                    file_size = os.path.getsize(pluto_file_path)
                    print(f"sepl_18.se1のファイルサイズ: {file_size} bytes")
                    if file_size < 1000:
                        print("★★★ 重大な警告: ファイルサイズが非常に小さいです。これはGit LFSのポインターファイルである可能性が高いです。")
                        print("★★★ 解決策: あなたのリポジトリでGit LFSを有効にする必要があります。")
                else:
                    print("警告: 'ephe'フォルダに主要な天体暦ファイル('sepl_18.se1'など)が見つかりません。")
        except Exception as e:
            print(f"天体暦フォルダの検査中にエラーが発生しました: {e}")

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
