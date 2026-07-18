import os
import requests
import pandas as pd
import streamlit as st
import FinanceDataReader as fdr
import plotly.graph_objects as go
import io
import zipfile
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta
from dotenv import load_dotenv


# 환경설정 불러오기
load_dotenv()

from pykrx import stock as krx_stock

dart_api_key = os.getenv("DART_API_KEY")
krx_id = os.getenv("KRX_ID")
krx_pw = os.getenv("KRX_PW")

st.set_page_config(
    page_title="한국 주식 통합 분석",
    page_icon="📊",
    layout="wide"
)

st.title("📊 쭌~! 한국 주식 통합 분석 프로그램")

st.markdown(
    """
    <style>
    div[data-testid="stExpander"] summary p {
        font-size: 18px;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.write("한국 주식 차트와 OpenDART 공시를 한 화면에서 확인합니다.")


@st.cache_data(ttl=3600)
def load_stock_list():
    return fdr.StockListing("KRX")

@st.cache_data(ttl=3600)
def load_investor_trading(ticker):
    empty_result = {
        "기준일": "",
        "개인_5일": 0.0,
        "기관_5일": 0.0,
        "외국인_5일": 0.0,
        "개인_10일": 0.0,
        "기관_10일": 0.0,
        "외국인_10일": 0.0,
        "조회상태": "수급 데이터 없음"
    }

    if not krx_id or not krx_pw:
        empty_result["조회상태"] = "KRX 계정 정보 없음"
        return empty_result

    try:
        ticker = str(ticker).zfill(6)

        end_date = datetime.today()
        start_date = end_date - timedelta(days=30)

        trading_df = krx_stock.get_market_trading_value_by_date(
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            ticker
        )

        required_columns = ["개인", "기관합계", "외국인합계"]

        if trading_df.empty:
            return empty_result

        if not all(
            column in trading_df.columns
            for column in required_columns
        ):
            empty_result["조회상태"] = "수급 데이터 형식 확인 필요"
            return empty_result

        trading_df = trading_df[required_columns].copy()
        trading_df = trading_df.sort_index()

        recent_5_days = trading_df.tail(5)
        recent_10_days = trading_df.tail(10)

        five_day_sum = recent_5_days.sum() / 100_000_000
        ten_day_sum = recent_10_days.sum() / 100_000_000

        return {
            "기준일": pd.to_datetime(
                trading_df.index[-1]
            ).strftime("%Y-%m-%d"),
            "개인_5일": round(float(five_day_sum["개인"]), 1),
            "기관_5일": round(float(five_day_sum["기관합계"]), 1),
            "외국인_5일": round(float(five_day_sum["외국인합계"]), 1),
            "개인_10일": round(float(ten_day_sum["개인"]), 1),
            "기관_10일": round(float(ten_day_sum["기관합계"]), 1),
            "외국인_10일": round(float(ten_day_sum["외국인합계"]), 1),
            "조회상태": "정상"
        }

    except Exception as error:
        error_name = type(error).__name__

        print(
            f"[KRX 수급 조회 오류] "
            f"{error_name}: {error}"
        )

        safe_error = str(error).replace(krx_id or "", "***")

        empty_result["조회상태"] = (
            f"수급 조회 실패 ({error_name}: {safe_error})"
        )
        return empty_result

def calculate_flow_score(investor_data):
    flow_score = 50

    if investor_data.get("조회상태") != "정상":
        return 50

    if investor_data["기관_5일"] > 0:
        flow_score += 10
    elif investor_data["기관_5일"] < 0:
        flow_score -= 10

    if investor_data["외국인_5일"] > 0:
        flow_score += 10
    elif investor_data["외국인_5일"] < 0:
        flow_score -= 10

    if (
        investor_data["기관_5일"] > 0
        and investor_data["외국인_5일"] > 0
    ):
        flow_score += 10

    if (
        investor_data["기관_10일"] > 0
        and investor_data["외국인_10일"] > 0
    ):
        flow_score += 10

    if (
        investor_data["개인_5일"] < 0
        and (
            investor_data["기관_5일"] > 0
            or investor_data["외국인_5일"] > 0
        )
    ):
        flow_score += 5

    if (
        investor_data["개인_5일"] > 0
        and investor_data["기관_5일"] < 0
        and investor_data["외국인_5일"] < 0
    ):
        flow_score -= 5

    return max(
        0,
        min(100, flow_score)
    )

@st.cache_data(ttl=86400)
def load_dart_corp_codes():
    url = "https://opendart.fss.or.kr/api/corpCode.xml"

    params = {
        "crtfc_key": dart_api_key
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=5
        )

        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            xml_data = zip_file.read("CORPCODE.xml")

        root = ET.fromstring(xml_data)

        corp_list = []

        for item in root.findall("list"):
            stock_code_value = item.findtext("stock_code", "").strip()

            if stock_code_value:
                corp_list.append({
                    "corp_code": item.findtext("corp_code", "").strip(),
                    "corp_name": item.findtext("corp_name", "").strip(),
                    "stock_code": stock_code_value
                })

        return pd.DataFrame(corp_list)

    except requests.exceptions.Timeout:
        return pd.DataFrame(
            columns=["corp_code", "corp_name", "stock_code"]
        )

    except requests.exceptions.RequestException:
        return pd.DataFrame(
            columns=["corp_code", "corp_name", "stock_code"]
        )

    except Exception:
        return pd.DataFrame(
            columns=["corp_code", "corp_name", "stock_code"]
        )

def analyze_disclosure(title):
    title = str(title).replace(" ", "")

    risk_rules = [
        (
            ["상장폐지", "상장적격성실질심사"],
            0,
            "상장폐지 또는 상장 적격성 관련 공시입니다."
        ),
        (
            ["횡령", "배임"],
            0,
            "횡령·배임 관련 위험 공시입니다."
        ),
        (
            ["감사의견거절", "의견거절", "한정의견"],
            5,
            "감사의견 관련 위험 공시입니다."
        ),
        (
            ["거래정지", "매매거래정지"],
            10,
            "주식 거래정지 관련 공시입니다."
        ),
        (
            ["불성실공시"],
            15,
            "불성실공시 관련 내용입니다."
        ),
        (
            ["관리종목"],
            15,
            "관리종목 지정 관련 내용입니다."
        ),
        (
            ["유상증자"],
            25,
            "유상증자로 주식 수 증가 가능성이 있습니다."
        ),
        (
            ["전환사채", "신주인수권부사채", "교환사채"],
            30,
            "향후 주식 전환에 따른 물량 증가 가능성이 있습니다."
        )
    ]

    for keywords, score, reason in risk_rules:
        for keyword in keywords:
            if keyword in title:
                return "위험 확인", score, reason

    positive_rules = [
        (
            [
                "단일판매ㆍ공급계약체결",
                "단일판매·공급계약체결",
                "단일판매공급계약체결"
            ],
            85,
            "단일판매·공급계약 체결 공시입니다."
        ),
        (
            ["대규모수주", "수주계약체결"],
            85,
            "대규모 수주 또는 계약 체결 공시입니다."
        ),
        (
            ["무상증자"],
            80,
            "무상증자 관련 공시입니다."
        ),
        (
            ["자기주식취득", "자사주취득"],
            75,
            "자기주식 취득 관련 공시입니다."
        ),
        (
            ["신규시설투자", "시설투자"],
            70,
            "신규 시설투자 관련 공시입니다."
        ),
        (
            ["특허권취득", "특허취득"],
            65,
            "특허 취득 관련 공시입니다."
        ),
        (
            ["공급계약", "계약체결"],
            65,
            "공급계약 또는 계약 체결 관련 공시입니다."
        )
    ]

    for keywords, score, reason in positive_rules:
        for keyword in keywords:
            if keyword in title:
                return "긍정 후보", score, reason

    neutral_rules = [
        (
            ["풍문또는보도에대한해명", "풍문또는보도"],
            "풍문이나 보도에 대한 해명 공시입니다."
        ),
        (
            ["조회공시"],
            "조회공시 답변 내용의 추가 확인이 필요합니다."
        ),
        (
            ["정정신고", "정정공시"],
            "기존 공시의 정정 내용 확인이 필요합니다."
        ),
        (
            ["주주총회", "주주총회소집"],
            "주주총회 관련 일반 공시입니다."
        )
    ]

    for keywords, reason in neutral_rules:
        for keyword in keywords:
            if keyword in title:
                return "중립·추가 확인", 50, reason

    return (
        "중립·추가 확인",
        50,
        "등록된 주요 긍정·위험 기준에 해당하지 않습니다."
    )

def calculate_watchlist_scores(stock_code):
    stock_code = str(stock_code).zfill(6)

    # ------------------------------------------
    # 1. 차트 점수 계산
    # ------------------------------------------
    start_date = datetime.today() - timedelta(days=90)

    stock_data = fdr.DataReader(
        stock_code,
        start_date.strftime("%Y-%m-%d")
    )

    if len(stock_data) < 20:
        raise ValueError(
            "점수를 계산할 주가 데이터가 부족합니다."
        )

    stock_data["5일선"] = (
        stock_data["Close"].rolling(5).mean()
    )

    stock_data["20일선"] = (
        stock_data["Close"].rolling(20).mean()
    )

    stock_data["20일평균거래량"] = (
        stock_data["Volume"].rolling(20).mean()
    )

    latest = stock_data.iloc[-1]

    current_price = latest["Close"]
    ma5 = latest["5일선"]
    ma20 = latest["20일선"]
    current_volume = latest["Volume"]
    average_volume = latest["20일평균거래량"]

    if pd.isna(ma5) or pd.isna(ma20):
        raise ValueError(
            "이동평균선을 계산할 데이터가 부족합니다."
        )

    if average_volume > 0:
        volume_ratio = current_volume / average_volume
    else:
        volume_ratio = 0

    chart_score = 50

    if current_price > ma5:
        chart_score += 10
    else:
        chart_score -= 10

    if current_price > ma20:
        chart_score += 15
    else:
        chart_score -= 15

    if ma5 > ma20:
        chart_score += 15
    else:
        chart_score -= 15

    if volume_ratio >= 2:
        chart_score += 20
    elif volume_ratio >= 1:
        chart_score += 10
    else:
        chart_score -= 5

    chart_score = max(
        0,
        min(100, int(chart_score))
    )

    # ------------------------------------------
    # 2. 공시 점수 계산
    # ------------------------------------------
    disclosure_score = 50

    corp_codes = load_dart_corp_codes()

    matched_corp = corp_codes[
        corp_codes["stock_code"] == stock_code
    ]

    if not matched_corp.empty:
        corp_code = matched_corp.iloc[0]["corp_code"]

        today = datetime.today()
        disclosure_start = today - timedelta(days=30)

        dart_url = (
            "https://opendart.fss.or.kr/api/list.json"
        )

        dart_params = {
            "crtfc_key": dart_api_key,
            "corp_code": corp_code,
            "bgn_de": disclosure_start.strftime("%Y%m%d"),
            "end_de": today.strftime("%Y%m%d"),
            "page_count": 100
        }

        dart_response = requests.get(
            dart_url,
            params=dart_params,
            timeout=10
        )

        dart_result = dart_response.json()

        if dart_result.get("status") == "000":
            positive_scores = []
            risk_count = 0

            for item in dart_result["list"]:
                category, score, _ = analyze_disclosure(
                    item["report_nm"]
                )

                if category == "긍정 후보":
                    positive_scores.append(score)

                if category == "위험 확인":
                    risk_count += 1

            if positive_scores:
                disclosure_score = max(
                    positive_scores
                )

            disclosure_score -= risk_count * 15

            disclosure_score = max(
                0,
                min(100, int(disclosure_score))
            )

    # ------------------------------------------
    # 3. 종합 점수와 등급 계산
    # ------------------------------------------
    total_score = round(
        chart_score * 0.4
        + disclosure_score * 0.6
    )

    if total_score >= 85:
        grade = "A"
    elif total_score >= 70:
        grade = "B"
    elif total_score >= 55:
        grade = "C"
    else:
        grade = "D"

    if disclosure_score >= 70 and chart_score >= 80:
        status_summary = "공시·차트 모두 긍정"
    elif disclosure_score >= 70:
        status_summary = "공시 긍정·차트 확인 필요"
    elif chart_score >= 80:
        status_summary = "차트 강함·공시 중립"
    elif disclosure_score < 40:
        status_summary = "위험 공시 확인 필요"
    else:
        status_summary = "중립 관찰"

    return {
        "차트 점수": chart_score,
        "공시 점수": disclosure_score,
        "종합 점수": total_score,
        "종합 등급": grade,
        "상태 요약": status_summary
    }

def should_save_score_history(history_file, history_row):
    if not os.path.exists(history_file):
        return True

    try:
        existing_history_df = pd.read_csv(
            history_file,
            dtype={"종목코드": str}
        )

        if existing_history_df.empty:
            return True

        stock_code = str(
            history_row["종목코드"]
        ).zfill(6)

        existing_history_df["종목코드"] = (
            existing_history_df["종목코드"]
            .astype(str)
            .str.zfill(6)
        )

        stock_history_df = existing_history_df[
            existing_history_df["종목코드"] == stock_code
        ].copy()

        if stock_history_df.empty:
            return True

        stock_history_df["기록일시"] = pd.to_datetime(
            stock_history_df["기록일시"],
            errors="coerce"
        )

        stock_history_df = (
            stock_history_df.dropna(
                subset=["기록일시"]
            )
            .sort_values(
                by="기록일시",
                ascending=False
            )
        )

        if stock_history_df.empty:
            return True

        latest_history = stock_history_df.iloc[0]

        new_record_time = pd.to_datetime(
            history_row["기록일시"],
            errors="coerce"
        )

        if pd.isna(new_record_time):
            return True

        same_day = (
            latest_history["기록일시"].date()
            == new_record_time.date()
        )

        same_chart_score = (
            int(float(latest_history["현재 차트 점수"]))
            == int(float(history_row["현재 차트 점수"]))
        )

        same_disclosure_score = (
            int(float(latest_history["현재 공시 점수"]))
            == int(float(history_row["현재 공시 점수"]))
        )

        same_total_score = (
            int(float(latest_history["현재 종합 점수"]))
            == int(float(history_row["현재 종합 점수"]))
        )

        same_grade = (
            str(latest_history["현재 등급"])
            == str(history_row["현재 등급"])
        )

        if (
            same_day
            and same_chart_score
            and same_disclosure_score
            and same_total_score
            and same_grade
        ):
            return False

        return True

    except Exception:
        return True

def clean_duplicate_score_history(history_file):
    if not os.path.exists(history_file):
        return {
            "status": "no_file",
            "removed_count": 0,
            "backup_file": ""
        }

    history_df = pd.read_csv(
        history_file,
        dtype={"종목코드": str}
    )

    if history_df.empty:
        return {
            "status": "empty",
            "removed_count": 0,
            "backup_file": ""
        }

    required_columns = [
        "종목코드",
        "기록일시",
        "현재 차트 점수",
        "현재 공시 점수",
        "현재 종합 점수",
        "현재 등급"
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in history_df.columns
    ]

    if missing_columns:
        raise ValueError(
            "중복 정리에 필요한 열이 없습니다: "
            + ", ".join(missing_columns)
        )

    original_count = len(history_df)

    history_df["종목코드"] = (
        history_df["종목코드"]
        .astype(str)
        .str.zfill(6)
    )

    history_df["_기록일시_정렬"] = pd.to_datetime(
        history_df["기록일시"],
        errors="coerce"
    )

    history_df["_기록날짜"] = (
        history_df["_기록일시_정렬"]
        .dt.strftime("%Y-%m-%d")
    )

    history_df["_기록날짜"] = (
        history_df["_기록날짜"]
        .fillna(
            history_df["기록일시"]
            .astype(str)
            .str[:10]
        )
    )

    score_columns = [
        "현재 차트 점수",
        "현재 공시 점수",
        "현재 종합 점수"
    ]

    for score_column in score_columns:
        history_df[
            f"_비교_{score_column}"
        ] = pd.to_numeric(
            history_df[score_column],
            errors="coerce"
        ).fillna(-999999)

    history_df["_비교_현재등급"] = (
        history_df["현재 등급"]
        .astype(str)
        .str.strip()
    )

    history_df = history_df.sort_values(
        by="_기록일시_정렬",
        ascending=False,
        na_position="last"
    )

    duplicate_columns = [
        "종목코드",
        "_기록날짜",
        "_비교_현재 차트 점수",
        "_비교_현재 공시 점수",
        "_비교_현재 종합 점수",
        "_비교_현재등급"
    ]

    cleaned_history_df = history_df.drop_duplicates(
        subset=duplicate_columns,
        keep="first"
    ).copy()

    cleaned_history_df = cleaned_history_df.sort_values(
        by="_기록일시_정렬",
        ascending=True,
        na_position="last"
    )

    helper_columns = [
        "_기록일시_정렬",
        "_기록날짜",
        "_비교_현재 차트 점수",
        "_비교_현재 공시 점수",
        "_비교_현재 종합 점수",
        "_비교_현재등급"
    ]

    cleaned_history_df = cleaned_history_df.drop(
        columns=helper_columns
    )

    removed_count = (
        original_count - len(cleaned_history_df)
    )

    if removed_count == 0:
        return {
            "status": "no_duplicates",
            "removed_count": 0,
            "backup_file": ""
        }

    backup_file = (
        "watchlist_history_backup_"
        + datetime.today().strftime("%Y%m%d_%H%M%S")
        + ".csv"
    )

    pd.read_csv(
        history_file,
        dtype={"종목코드": str}
    ).to_csv(
        backup_file,
        index=False,
        encoding="utf-8-sig"
    )

    cleaned_history_df.to_csv(
        history_file,
        index=False,
        encoding="utf-8-sig"
    )

    return {
        "status": "cleaned",
        "removed_count": removed_count,
        "backup_file": backup_file
    }

def restore_latest_score_history_backup():
    backup_files = [
        file_name
        for file_name in os.listdir(".")
        if (
            file_name.startswith(
                "watchlist_history_backup_"
            )
            and file_name.endswith(".csv")
        )
    ]

    if not backup_files:
        return {
            "status": "no_backup",
            "backup_file": ""
        }

    backup_files = sorted(
        backup_files,
        reverse=True
    )

    latest_backup_file = backup_files[0]

    backup_df = pd.read_csv(
        latest_backup_file,
        dtype={"종목코드": str}
    )

    backup_df.to_csv(
        "watchlist_history.csv",
        index=False,
        encoding="utf-8-sig"
    )

    return {
        "status": "restored",
        "backup_file": latest_backup_file
    }

stocks = load_stock_list()

tab1, tab2, tab3, tab4 = st.tabs([
    "📈 종목 차트 분석",
    "📋 전체 공시 분석",
    "🔎 추천 후보 찾기",
    "⭐ 관심종목"
])


# --------------------------------------------------
# 첫 번째 탭: 차트 분석
# --------------------------------------------------
with tab1:
    st.subheader("종목 차트 분석")

    stock_name = st.selectbox(
        "종목명을 선택하세요",
        stocks["Name"].tolist()
    )

    stock_code = stocks.loc[
        stocks["Name"] == stock_name,
        "Code"
    ].iloc[0]

    previous_stock_code = st.session_state.get("previous_stock_code")

    if previous_stock_code != stock_code:
        st.session_state.pop("chart_score", None)
        st.session_state.pop("chart_stock_code", None)
        st.session_state.pop("disclosure_score", None)
        st.session_state.pop("disclosure_stock_code", None)
        st.session_state.pop("positive_count", None)
        st.session_state.pop("risk_count", None)

        st.session_state["previous_stock_code"] = stock_code

    st.write(f"선택 종목코드: **{stock_code}**")

    st.subheader("선택 종목 최근 공시")

    disclosure_days = st.selectbox(
        "최근 공시 조회 기간",
        [7, 30, 90],
        index=1,
        key="selected_stock_days"
    )

    if st.button("선택 종목 공시 불러오기", key="selected_stock_dart"):
        try:
            corp_codes = load_dart_corp_codes()

            matched_corp = corp_codes[
                corp_codes["stock_code"] == stock_code
            ]

            if matched_corp.empty:
                st.warning("해당 종목의 DART 회사코드를 찾지 못했습니다.")

            else:
                corp_code = matched_corp.iloc[0]["corp_code"]

                today = datetime.today()
                start_day = today - timedelta(days=disclosure_days)

                url = "https://opendart.fss.or.kr/api/list.json"

                params = {
                    "crtfc_key": dart_api_key,
                    "corp_code": corp_code,
                    "bgn_de": start_day.strftime("%Y%m%d"),
                    "end_de": today.strftime("%Y%m%d"),
                    "page_count": 100
                }

                response = requests.get(
                    url,
                    params=params,
                    timeout=10
                )

                result = response.json()

                if result.get("status") == "000":
                    selected_disclosures = []

                    for item in result["list"]:
                        title = item["report_nm"]
                        category, score, reason = analyze_disclosure(title)

                        selected_disclosures.append({
                            "공시 제목": title,
                            "자동 분류": category,
                            "중요도 점수": score,
                            "판단 근거": reason,
                            "공시 날짜": item["rcept_dt"],
                            "공시 원문": (
                                "https://dart.fss.or.kr/"
                                "dsaf001/main.do?"
                                f"rcpNo={item['rcept_no']}"
                            )
                        })

                    selected_df = pd.DataFrame(selected_disclosures)

                    positive_count = len(
                        selected_df[
                           selected_df["자동 분류"] == "긍정 후보"
                        ]
                    )

                    risk_count = len(
                        selected_df[
                           selected_df["자동 분류"] == "위험 확인"
                        ]
                    )

                    if positive_count > 0:
                        positive_scores = selected_df[
                            selected_df["자동 분류"] == "긍정 후보"
                        ]["중요도 점수"]

                        disclosure_score = int(positive_scores.max())
                    else:
                        disclosure_score = 50

                    # 위험 공시 1건당 15점 감점
                    disclosure_score -= risk_count * 15

                    disclosure_score = max(0, min(100, disclosure_score))

                    st.session_state["disclosure_score"] = disclosure_score
                    st.session_state["disclosure_stock_code"] = stock_code
                    st.session_state["positive_count"] = positive_count
                    st.session_state["risk_count"] = risk_count

                    st.success(
                        f"{stock_name} 공시 "
                        f"{len(selected_df)}건을 찾았습니다."
                    )

                    st.dataframe(
                        selected_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "공시 원문": st.column_config.LinkColumn(
                                "공시 원문",
                                display_text="원문 보기"
                            )
                        }
                    )

                elif result.get("status") == "013":
                    st.info(
                        f"최근 {disclosure_days}일 동안 "
                        f"{stock_name} 공시가 없습니다."
                    )

                else:
                    st.error(result.get("message"))

        except Exception as error:
            st.error(f"선택 종목 공시 조회 오류: {error}")

    if st.button("차트 분석 시작", key="chart_button"):
        try:
            start_date = datetime.today() - timedelta(days=180)

            data = fdr.DataReader(
                stock_code,
                start_date.strftime("%Y-%m-%d")
            )

            if data.empty:
                st.warning("주가 데이터가 없습니다.")
            else:
                data["5일선"] = data["Close"].rolling(5).mean()
                data["20일선"] = data["Close"].rolling(20).mean()
                data["20일평균거래량"] = (
                    data["Volume"].rolling(20).mean()
                )

                chart = go.Figure()

                chart.add_trace(
                    go.Candlestick(
                        x=data.index,
                        open=data["Open"],
                        high=data["High"],
                        low=data["Low"],
                        close=data["Close"],
                        name="주가"
                    )
                )

                chart.add_trace(
                    go.Scatter(
                        x=data.index,
                        y=data["5일선"],
                        name="5일선"
                    )
                )

                chart.add_trace(
                    go.Scatter(
                        x=data.index,
                        y=data["20일선"],
                        name="20일선"
                    )
                )

                chart.update_layout(
                    title=f"{stock_name} 주가 차트",
                    xaxis_rangeslider_visible=False,
                    height=600
                )

                st.plotly_chart(chart, width="stretch")

                latest = data.iloc[-1]

                current_price = latest["Close"]
                ma5 = latest["5일선"]
                ma20 = latest["20일선"]
                current_volume = latest["Volume"]
                average_volume = latest["20일평균거래량"]

                if average_volume > 0:
                    volume_ratio = current_volume / average_volume
                else:
                    volume_ratio = 0

                st.subheader("차트 자동 분석")

                col1, col2, col3 = st.columns(3)

                col1.metric(
                    "최근 종가",
                    f"{current_price:,.0f}원"
                )

                col2.metric(
                    "5일 이동평균선",
                    f"{ma5:,.0f}원"
                )

                col3.metric(
                    "20일 이동평균선",
                    f"{ma20:,.0f}원"
                )

                if current_price > ma5:
                    st.success("현재 주가는 5일선 위에 있습니다.")
                else:
                    st.warning("현재 주가는 5일선 아래에 있습니다.")

                if current_price > ma20:
                    st.success("현재 주가는 20일선 위에 있습니다.")
                else:
                    st.error("현재 주가는 20일선 아래에 있습니다.")

                if ma5 > ma20:
                    st.info(
                        "5일선이 20일선보다 높아 "
                        "단기 흐름이 상대적으로 강합니다."
                    )
                else:
                    st.warning(
                        "5일선이 20일선보다 낮아 "
                        "단기 흐름이 약한 상태입니다."
                    )

                st.subheader("거래량 자동 분석")

                col4, col5 = st.columns(2)

                col4.metric(
                    "최근 거래량",
                    f"{current_volume:,.0f}주"
                )

                col5.metric(
                    "20일 평균 대비",
                    f"{volume_ratio:.2f}배"
                )

                if volume_ratio >= 2:
                    st.success(
                        "최근 거래량이 20일 평균보다 "
                        "2배 이상 증가했습니다."
                    )
                elif volume_ratio >= 1:
                    st.info(
                        "최근 거래량이 20일 평균보다 증가했습니다."
                    )
                else:
                    st.warning(
                        "최근 거래량이 20일 평균보다 적습니다."
                    )

                score = 50

                if current_price > ma5:
                    score += 10
                else:
                    score -= 10

                if current_price > ma20:
                    score += 15
                else:
                    score -= 15

                if ma5 > ma20:
                    score += 15
                else:
                    score -= 15

                if volume_ratio >= 2:
                    score += 20
                elif volume_ratio >= 1:
                    score += 10
                else:
                    score -= 5

                score = max(0, min(100, score))

                st.session_state["chart_score"] = score
                st.session_state["chart_stock_code"] = stock_code

                st.subheader("차트 종합 평가")
                st.metric(
                    "차트 점수",
                    f"{score}점 / 100점"
                )

                if score >= 80:
                    st.success("차트 흐름이 강한 상태입니다.")
                elif score >= 50:
                    st.info("차트 흐름은 보통입니다.")
                else:
                    st.error("현재 차트 흐름은 약한 상태입니다.")

        except Exception as error:
            st.error(f"주가 데이터를 불러오지 못했습니다: {error}")


# --------------------------------------------------
# 두 번째 탭: 전체 공시 분석
# --------------------------------------------------

        st.divider()
        st.subheader("선택 종목 종합 평가")

    chart_ready = (
        st.session_state.get("chart_stock_code") == stock_code
    )

    disclosure_ready = (
        st.session_state.get("disclosure_stock_code") == stock_code
    )

    if chart_ready and disclosure_ready:
        chart_score = st.session_state["chart_score"]
        disclosure_score = st.session_state["disclosure_score"]

        total_score = round(
            chart_score * 0.4
            + disclosure_score * 0.6
        )

        col_a, col_b, col_c = st.columns(3)

        col_a.metric("차트 점수", f"{chart_score}점")
        col_b.metric("공시 점수", f"{disclosure_score}점")
        col_c.metric("종합 관찰 점수", f"{total_score}점")

        if disclosure_score >= 70:
            disclosure_status = "긍정"
        elif disclosure_score >= 40:
            disclosure_status = "중립"
        else:
            disclosure_status = "위험"

        if chart_score >= 80:
            chart_status = "강함"
        elif chart_score >= 50:
            chart_status = "보통"
        else:
            chart_status = "약함"

        st.write(f"공시 상태: **{disclosure_status}**")
        st.write(f"차트 상태: **{chart_status}**")

        positive_count = st.session_state.get("positive_count", 0)
        risk_count = st.session_state.get("risk_count", 0)

        st.subheader("자동 판단 근거")

        st.write(f"긍정 공시: **{positive_count}건**")
        st.write(f"위험 공시: **{risk_count}건**")
        st.write(f"차트 상태: **{chart_status}**")

        if positive_count == 0 and risk_count == 0:
            st.info(
                "최근 공시에서 뚜렷한 긍정·위험 키워드가 "
                "확인되지 않았습니다."
            )
        elif risk_count > positive_count:
            st.warning(
                "긍정 공시보다 위험 공시가 많아 "
                "추가 확인이 필요합니다."
            )
        elif positive_count > risk_count:
            st.success("위험 공시보다 긍정 공시가 많습니다.")
        else:
            st.info("긍정 공시와 위험 공시가 함께 확인됐습니다.")

        st.subheader("최종 한 줄 요약")

        if disclosure_status == "긍정" and chart_status == "강함":
            st.success(
                "공시와 차트가 모두 긍정적인 강한 관찰 후보입니다."
            )
        elif disclosure_status == "긍정":
            st.info(
                "공시는 긍정적이지만 차트 흐름은 "
                "추가 확인이 필요합니다."
            )
        elif disclosure_status == "위험":
            st.error(
                "위험 공시가 확인되어 매수 판단 전에 "
                "원문 확인이 필요합니다."
            )
        elif chart_status == "약함":
            st.warning(
                "공시는 중립이지만 단기 차트 흐름은 약한 상태입니다."
            )
        else:
            st.info(
                "공시와 차트 모두 뚜렷한 강점이 없는 "
                "중립 관찰 단계입니다."
            )

with tab2:
    st.subheader("OpenDART 전체 공시 분석")

    if st.button("OpenDART 연결 진단", key="dart_connection_test"):
        test_results = []

        try:
            homepage_response = requests.get(
                "https://opendart.fss.or.kr",
                timeout=10
            )
            test_results.append(
                f"홈페이지 연결: 성공 ({homepage_response.status_code})"
            )
        except requests.exceptions.Timeout:
            test_results.append("홈페이지 연결: 시간 초과")
        except requests.exceptions.RequestException:
            test_results.append("홈페이지 연결: 실패")

        try:
            api_response = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                timeout=10
            )
            test_results.append(
                f"API 주소 연결: 성공 ({api_response.status_code})"
            )
        except requests.exceptions.Timeout:
            test_results.append("API 주소 연결: 시간 초과")
        except requests.exceptions.RequestException:
            test_results.append("API 주소 연결: 실패")

        for result_text in test_results:
            st.write(result_text)

    days = st.selectbox(
        "최근 며칠간 공시를 볼까요?",
        [1, 3, 7, 14],
        index=2
    )

    if st.button("최근 공시 불러오기", key="dart_button"):
        if not dart_api_key:
            st.error("DART API 키를 찾지 못했습니다.")
        else:
            today = datetime.today()
            start_day = today - timedelta(days=days)

            url = "https://opendart.fss.or.kr/api/list.json"

            params = {
                "crtfc_key": dart_api_key,
                "bgn_de": start_day.strftime("%Y%m%d"),
                "end_de": today.strftime("%Y%m%d"),
                "page_count": 100
            }

            try:
                response = requests.get(
                    url,
                    params=params,
                    timeout=30
                )

                result = response.json()

                if result.get("status") == "000":
                    disclosure_list = []

                    for item in result["list"]:
                        title = item["report_nm"]

                        category, score, reason = (
                            analyze_disclosure(title)
                        )

                        disclosure_list.append({
                            "회사명": item["corp_name"],
                            "공시 제목": title,
                            "자동 분류": category,
                            "중요도 점수": score,
                            "판단 근거": reason,
                            "공시 날짜": item["rcept_dt"],
                            "공시 원문": (
                                "https://dart.fss.or.kr/"
                                "dsaf001/main.do?"
                                f"rcpNo={item['rcept_no']}"
                            )
                        })

                    dataframe = pd.DataFrame(disclosure_list)

                    dataframe = dataframe.sort_values(
                        by="중요도 점수",
                        ascending=False
                    )

                    st.session_state["dart_data"] = dataframe

                else:
                    st.error(result.get("message"))

            except requests.exceptions.Timeout:
                st.error(
                    "OpenDART 서버 연결 시간이 초과되었습니다. "
                    "잠시 후 다시 시도해주세요."
                )

            except requests.exceptions.RequestException:
                st.error(
                    "OpenDART 서버와 통신하지 못했습니다. "
                    "인터넷 연결 또는 서버 상태를 확인해주세요."
                )

            except Exception:
                st.error(
                    "공시 조회 중 오류가 발생했습니다. "
                    "잠시 후 다시 시도해주세요."
                )

    if "dart_data" in st.session_state:
        dataframe = st.session_state["dart_data"].copy()

        st.success(
            f"공시 {len(dataframe)}건을 가져왔습니다."
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "긍정 후보",
            len(
                dataframe[
                    dataframe["자동 분류"] == "긍정 후보"
                ]
            )
        )

        col2.metric(
            "위험 확인",
            len(
                dataframe[
                    dataframe["자동 분류"] == "위험 확인"
                ]
            )
        )

        col3.metric(
            "추가 확인",
            len(
                dataframe[
                    dataframe["자동 분류"] == "중립·추가 확인"
                ]
            )
        )

        selected_category = st.selectbox(
            "분류를 선택하세요",
            [
                "전체",
                "긍정 후보",
                "위험 확인",
                "중립·추가 확인"
            ]
        )

        company_search = st.text_input(
            "회사명을 검색하세요",
            placeholder="예: 삼성전자, 우리기술, 에이피알"
        )

        minimum_score = st.slider(
            "최소 중요도 점수",
            min_value=0,
            max_value=100,
            value=0,
            step=5
        )

        if selected_category != "전체":
            dataframe = dataframe[
                dataframe["자동 분류"] == selected_category
            ]

        if company_search:
            dataframe = dataframe[
                dataframe["회사명"].str.contains(
                    company_search,
                    case=False,
                    na=False
                )
            ]

        dataframe = dataframe[
            dataframe["중요도 점수"] >= minimum_score
        ]

        st.dataframe(
            dataframe,
            width="stretch",
            hide_index=True,
            column_config={
                "공시 원문": st.column_config.LinkColumn(
                    "공시 원문",
                    display_text="원문 보기"
                )
            }
        )
# --------------------------------------------------
# 세 번째 탭: 추천 후보 찾기
# --------------------------------------------------
with tab3:
    st.subheader("추천 후보 찾기")

    st.write("원하는 조건을 직접 설정하세요.")

    col1, col2 = st.columns(2)

    with col1:
        use_ma5 = st.checkbox(
            "현재가가 5일선 위",
            value=True
        )

        use_ma20 = st.checkbox(
            "현재가가 20일선 위",
            value=True
        )

        use_ma_order = st.checkbox(
            "5일선이 20일선 위",
            value=True
        )

    with col2:
        minimum_volume_ratio = st.slider(
            "최소 거래량 배수",
            min_value=0.0,
            max_value=5.0,
            value=1.0,
            step=0.1
        )

        minimum_chart_score = st.slider(
            "최소 차트 점수",
            min_value=0,
            max_value=100,
            value=50,
            step=5
        )

        maximum_results = st.selectbox(
            "최대 결과 종목 수",
            [10, 20, 30, 50],
            index=1
        )

        market_filter = st.selectbox(
            "검색할 시장",
            ["전체", "KOSPI", "KOSDAQ"],
            index=0
        )

        scan_count = st.selectbox(
            "분석할 종목 수",
            [30, 100, 300, 500],
            index=0
        )

        start_position = st.selectbox(
            "분석 시작 위치",
            [1, 101, 201, 301, 501, 1001, 1501, 2001],
            index=0
        )


    st.divider()

    st.write("현재 설정 조건")

    st.write(f"5일선 조건: **{'사용' if use_ma5 else '미사용'}**")
    st.write(f"20일선 조건: **{'사용' if use_ma20 else '미사용'}**")
    st.write(
        f"이동평균선 배열 조건: "
        f"**{'사용' if use_ma_order else '미사용'}**"
    )
    st.write(f"최소 거래량: **{minimum_volume_ratio:.1f}배**")
    st.write(f"최소 차트 점수: **{minimum_chart_score}점**")
    st.write(f"최대 결과: **{maximum_results}개**")

    if st.button("추천 후보 검색 시작", key="candidate_search"):

        search_started_at = datetime.now()

        if market_filter == "전체":
            filtered_stocks = stocks.copy()

        elif market_filter == "KOSPI":
            filtered_stocks = stocks[
                stocks["Market"] == "KOSPI"
            ].copy()

        else:
            filtered_stocks = stocks[
                stocks["Market"].isin(
                    ["KOSDAQ", "KOSDAQ GLOBAL"]
                )
            ].copy()

        start_index = start_position - 1
        end_index = start_index + scan_count

        test_stocks = filtered_stocks.iloc[start_index:end_index]

        st.info(
            f"{market_filter} 시장의 "
            f"{start_position}번째부터 "
            f"{len(test_stocks)}개를 분석합니다."
        )

        st.session_state["candidate_search_conditions"] = {
            "분석 시장": market_filter,
            "분석 시작 위치": start_position,
            "분석 종목 수": len(test_stocks),
            "5일선 조건": "사용" if use_ma5 else "미사용",
            "20일선 조건": "사용" if use_ma20 else "미사용",
            "이동평균선 배열 조건": "사용" if use_ma_order else "미사용",
            "최소 거래량 배수": minimum_volume_ratio,
            "최소 차트 점수": minimum_chart_score,
            "최대 결과 수": maximum_results
        }

        progress_bar = st.progress(0)
        status_text = st.empty()

        candidate_list = []
        success_count = 0
        error_count = 0

        for index, (_, stock) in enumerate(test_stocks.iterrows()):
            stock_name_value = stock["Name"]
            stock_code_value = stock["Code"]
            market_value = stock["Market"]

            status_text.write(
                f"분석 중: {stock_name_value} "
                f"({index + 1}/{len(test_stocks)})"
            )

            try:
                start_date = datetime.today() - timedelta(days=90)

                stock_data = fdr.DataReader(
                    stock_code_value,
                    start_date.strftime("%Y-%m-%d")
                )

                if len(stock_data) < 20:
                    continue

                stock_data["5일선"] = (
                    stock_data["Close"].rolling(5).mean()
                )

                stock_data["20일선"] = (
                    stock_data["Close"].rolling(20).mean()
                )

                stock_data["20일평균거래량"] = (
                    stock_data["Volume"].rolling(20).mean()
                )

                latest = stock_data.iloc[-1]

                current_price = latest["Close"]
                ma5 = latest["5일선"]
                ma20 = latest["20일선"]
                current_volume = latest["Volume"]
                average_volume = latest["20일평균거래량"]

                if pd.isna(ma5) or pd.isna(ma20):
                    continue

                if average_volume > 0:
                    volume_ratio = current_volume / average_volume
                else:
                    volume_ratio = 0

                chart_score = 50

                if current_price > ma5:
                    chart_score += 10
                else:
                    chart_score -= 10

                if current_price > ma20:
                    chart_score += 15
                else:
                    chart_score -= 15

                if ma5 > ma20:
                    chart_score += 15
                else:
                    chart_score -= 15

                if volume_ratio >= 2:
                    chart_score += 20
                elif volume_ratio >= 1:
                    chart_score += 10
                else:
                    chart_score -= 5

                chart_score = max(0, min(100, chart_score))

                passed = True

                if use_ma5 and current_price <= ma5:
                    passed = False

                if use_ma20 and current_price <= ma20:
                    passed = False

                if use_ma_order and ma5 <= ma20:
                    passed = False

                if volume_ratio < minimum_volume_ratio:
                    passed = False

                if chart_score < minimum_chart_score:
                    passed = False

                if passed:
                    candidate_list.append({
                        "종목명": stock_name_value,
                        "시장": market_value,
                        "종목코드": stock_code_value,
                        "최근 종가": int(current_price),
                        "5일선": int(ma5),
                        "20일선": int(ma20),
                        "거래량 배수": round(volume_ratio, 2),
                        "차트 점수": chart_score
                    })

                success_count += 1

            except Exception as error:
                error_count += 1

                print(
                    f"[추천 검색 오류] "
                    f"{stock_name_value}({stock_code_value}): {error}"
                )

            progress_bar.progress(
                int(((index + 1) / len(test_stocks)) * 100)
            )

        status_text.empty()
        progress_bar.empty()

        condition_fail_count = max(
            0,
            success_count - len(candidate_list)
        )

        st.session_state["candidate_search_stats"] = {
            "전체 분석 수": len(test_stocks),
            "정상 처리 수": success_count,
            "조건 탈락 수": condition_fail_count,
            "오류 수": error_count,
            "추천 후보 수": len(candidate_list)
        }

        if candidate_list:
            candidate_df = pd.DataFrame(candidate_list)

            corp_codes = load_dart_corp_codes()
            disclosure_scores = []

            for _, row in candidate_df.iterrows():
                stock_code_value = row["종목코드"]

                matched_corp = corp_codes[
                    corp_codes["stock_code"] == stock_code_value
                ]

                if matched_corp.empty:
                    disclosure_scores.append(50)
                    continue

                corp_code = matched_corp.iloc[0]["corp_code"]

                today = datetime.today()
                start_day = today - timedelta(days=30)

                url = "https://opendart.fss.or.kr/api/list.json"

                params = {
                    "crtfc_key": dart_api_key,
                    "corp_code": corp_code,
                    "bgn_de": start_day.strftime("%Y%m%d"),
                    "end_de": today.strftime("%Y%m%d"),
                    "page_count": 100
                }

                try:
                    response = requests.get(
                        url,
                        params=params,
                        timeout=3
                    )

                    result = response.json()

                    if result.get("status") == "000":
                        temp_scores = []
                        risk_count = 0

                        for item in result["list"]:
                            category, score, _ = analyze_disclosure(
                                item["report_nm"]
                            )

                            if category == "긍정 후보":
                                temp_scores.append(score)

                            if category == "위험 확인":
                                risk_count += 1

                        if temp_scores:
                            disclosure_score = max(temp_scores)
                        else:
                            disclosure_score = 50

                        disclosure_score -= risk_count * 15
                        disclosure_score = max(
                            0,
                            min(100, disclosure_score)
                        )

                        disclosure_scores.append(disclosure_score)

                    else:
                        disclosure_scores.append(50)

                except Exception:
                    disclosure_scores.append(50)

            candidate_df["공시 점수"] = disclosure_scores

            candidate_df["종합 점수"] = (
                candidate_df["차트 점수"] * 0.4
                + candidate_df["공시 점수"] * 0.6
            ).round().astype(int)

            def make_grade(score):
                if score >= 85:
                    return "A"
                elif score >= 70:
                    return "B"
                elif score >= 55:
                    return "C"
                else:
                    return "D"

            def make_status(row):
                if row["공시 점수"] >= 70 and row["차트 점수"] >= 80:
                    return "공시·차트 모두 긍정"
                elif row["공시 점수"] >= 70:
                    return "공시 긍정·차트 확인 필요"
                elif row["차트 점수"] >= 80:
                    return "차트 강함·공시 중립"
                elif row["공시 점수"] < 40:
                    return "위험 공시 확인 필요"
                else:
                    return "중립 관찰"

            candidate_df["종합 등급"] = (
                candidate_df["종합 점수"].apply(make_grade)
            )

            candidate_df["상태 요약"] = candidate_df.apply(
                make_status,
                axis=1
            )
            def make_reason(row):
                reasons = []

                if row["차트 점수"] >= 80:
                    reasons.append("차트 조건 강함")
                elif row["차트 점수"] >= 60:
                    reasons.append("차트 조건 양호")

                if row["공시 점수"] >= 70:
                    reasons.append("긍정 공시 확인")

                if row["거래량 배수"] >= 2:
                    reasons.append("거래량 크게 증가")
                elif row["거래량 배수"] >= 1:
                    reasons.append("거래량 조건 충족")

                if not reasons:
                    reasons.append("뚜렷한 상승 근거 부족")

                return " · ".join(reasons)

            def make_warning(row):
                warnings = []

                if row["공시 점수"] < 40:
                    warnings.append("공시 위험 신호 존재")
                elif row["공시 점수"] < 70:
                    warnings.append("공시 내용 추가 확인 필요")

                if row["차트 점수"] < 60:
                    warnings.append("차트 흐름 약함")

                if row["거래량 배수"] < 1:
                    warnings.append("거래량 조건 미충족")

                if not warnings:
                    warnings.append("특별한 위험 신호 없음")

                return " · ".join(warnings)

            candidate_df["상승 근거"] = candidate_df.apply(
                make_reason,
                axis=1
            )

            candidate_df["주의 사항"] = candidate_df.apply(
                make_warning,
                axis=1
            )

            candidate_df["실시간 차트"] = (
                "https://finance.naver.com/item/main.naver?code="
                + candidate_df["종목코드"].astype(str).str.zfill(6)
            )

            candidate_df = candidate_df.sort_values(
                by=["종합 점수", "차트 점수", "거래량 배수"],
                ascending=False
            )

            candidate_df = candidate_df.head(maximum_results)

            flow_scores = []

            with st.spinner(
                "최종 추천 종목의 외국인·기관·개인 수급을 확인하고 있습니다..."
            ):
                for ticker in candidate_df["종목코드"]:
                    investor_data = load_investor_trading(
                        str(ticker).zfill(6)
                    )

                    flow_score = calculate_flow_score(
                        investor_data
                    )

                    flow_scores.append(flow_score)

            candidate_df["수급 점수"] = flow_scores

            candidate_df["수급 반영 점수"] = (
                candidate_df["종합 점수"] * 0.8
                + candidate_df["수급 점수"] * 0.2
            ).round().astype(int)

            candidate_df["최종 추천 등급"] = (
                candidate_df["수급 반영 점수"].apply(make_grade)
            )

            def make_short_opinion(grade):
                if grade == "A":
                    return "최우선 검토"
                elif grade == "B":
                    return "추가 확인"
                elif grade == "C":
                    return "신중 관찰"
                else:
                    return "우선순위 낮음"

            candidate_df["최종 추천 의견"] = (
                candidate_df["최종 추천 등급"].apply(make_short_opinion)
            )

            candidate_df = candidate_df.sort_values(
                by=[
                    "수급 반영 점수",
                    "종합 점수",
                    "수급 점수",
                    "차트 점수",
                    "거래량 배수"
                ],
                ascending=False
            ).reset_index(drop=True)

            st.session_state["candidate_results"] = candidate_df.copy()

            st.session_state["candidate_completed_at"] = (
               datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            search_elapsed_seconds = (
                datetime.now() - search_started_at
            ).total_seconds()

            st.session_state["candidate_search_elapsed"] = round(
                search_elapsed_seconds,
                1
            )

        else:
            st.session_state.pop("candidate_results", None)

            zero_completed_at = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            st.session_state["candidate_completed_at"] = zero_completed_at

            zero_search_elapsed_seconds = (
                datetime.now() - search_started_at
            ).total_seconds()

            st.session_state["candidate_search_elapsed"] = round(
                zero_search_elapsed_seconds,
                1
            )

            st.warning(
                "현재 조건을 통과한 추천 후보가 없습니다. "
                "검색 조건을 완화한 뒤 다시 시도해주세요."
            )

            st.caption(
                f"추천 분석 완료 시각: {zero_completed_at}"
            )

            zero_search_elapsed = st.session_state.get(
                "candidate_search_elapsed"
            )

            if zero_search_elapsed is not None:
                st.caption(
                    f"추천 분석 소요시간: {zero_search_elapsed:.1f}초"
                )

            zero_search_stats = st.session_state.get(
                "candidate_search_stats",
                {}
            )

            if zero_search_stats:
                st.caption(
                    "처리 결과: "
                    f"전체 {zero_search_stats['전체 분석 수']}개 · "
                    f"정상 처리 {zero_search_stats['정상 처리 수']}개 · "
                    f"조건 탈락 {zero_search_stats['조건 탈락 수']}개 · "
                    f"오류 {zero_search_stats['오류 수']}개 · "
                    f"추천 후보 {zero_search_stats['추천 후보 수']}개"
                )

    if "candidate_results" in st.session_state:
        candidate_df = st.session_state["candidate_results"].copy()

        st.success(
            f"조건을 통과한 종목 {len(candidate_df)}개를 찾았습니다."
        )

        completed_at = st.session_state.get(
            "candidate_completed_at",
            ""
        )

        if completed_at:
            st.caption(
                f"추천 분석 완료 시각: {completed_at}"
            )

        search_elapsed = st.session_state.get(
            "candidate_search_elapsed"
        )

        if search_elapsed is not None:
            st.caption(
                f"추천 분석 소요시간: {search_elapsed:.1f}초"
            )

        search_stats = st.session_state.get(
            "candidate_search_stats",
            {}
        )

        if search_stats:
            st.caption(
                "처리 결과: "
                f"전체 {search_stats['전체 분석 수']}개 · "
                f"정상 처리 {search_stats['정상 처리 수']}개 · "
                f"조건 탈락 {search_stats['조건 탈락 수']}개 · "
                f"오류 {search_stats['오류 수']}개 · "
                f"추천 후보 {search_stats['추천 후보 수']}개"
            )

        search_conditions = st.session_state.get(
            "candidate_search_conditions",
            {}
        )

        if search_conditions:
            st.caption(
                "검색 조건: "
                f"시장 {search_conditions['분석 시장']} · "
                f"시작 위치 {search_conditions['분석 시작 위치']} · "
                f"분석 종목 수 {search_conditions['분석 종목 수']}개"
            )

            st.caption(
                "필터 조건: "
                f"5일선 {search_conditions['5일선 조건']} · "
                f"20일선 {search_conditions['20일선 조건']} · "
                f"이동평균선 배열 {search_conditions['이동평균선 배열 조건']} · "
                f"최소 거래량 {search_conditions['최소 거래량 배수']:.1f}배 · "
                f"최소 차트 점수 {search_conditions['최소 차트 점수']}점 · "
                f"최대 결과 {search_conditions['최대 결과 수']}개"
            )

        st.dataframe(
            candidate_df,
            width="stretch",
            hide_index=True,
            column_config={
                "실시간 차트": st.column_config.LinkColumn(
                    "실시간 차트",
                    display_text="차트 보기"
                ),
                "수급 반영 점수": st.column_config.NumberColumn(
                    "최종 추천 점수",
                    format="%d점"
                )
            }
        )

        csv_export_df = candidate_df.copy()

        csv_completed_at = st.session_state.get(
            "candidate_completed_at",
            ""
        )

        csv_export_df["분석 완료 시각"] = csv_completed_at

        csv_search_elapsed = st.session_state.get(
            "candidate_search_elapsed",
            ""
        )

        csv_export_df["분석 소요시간(초)"] = csv_search_elapsed

        csv_search_stats = st.session_state.get(
            "candidate_search_stats",
            {}
        )

        csv_export_df["전체 분석 수"] = csv_search_stats.get(
            "전체 분석 수",
            ""
        )

        csv_export_df["정상 처리 수"] = csv_search_stats.get(
            "정상 처리 수",
            ""
        )

        csv_export_df["조건 탈락 수"] = csv_search_stats.get(
            "조건 탈락 수",
            ""
        )

        csv_export_df["오류 수"] = csv_search_stats.get(
            "오류 수",
            ""
        )

        csv_export_df["추천 후보 수"] = csv_search_stats.get(
            "추천 후보 수",
            ""
        )

        csv_search_conditions = st.session_state.get(
            "candidate_search_conditions",
            {}
        )

        csv_export_df["분석 시장"] = csv_search_conditions.get(
            "분석 시장",
            ""
        )

        csv_export_df["분석 시작 위치"] = csv_search_conditions.get(
            "분석 시작 위치",
            ""
        )

        csv_export_df["분석 종목 수"] = csv_search_conditions.get(
            "분석 종목 수",
            ""
        )

        csv_export_df["5일선 조건"] = csv_search_conditions.get(
            "5일선 조건",
            ""
        )

        csv_export_df["20일선 조건"] = csv_search_conditions.get(
            "20일선 조건",
            ""
        )

        csv_export_df["이동평균선 배열 조건"] = csv_search_conditions.get(
            "이동평균선 배열 조건",
            ""
        )

        csv_export_df["최소 거래량 배수"] = csv_search_conditions.get(
            "최소 거래량 배수",
            ""
        )

        csv_export_df["최소 차트 점수"] = csv_search_conditions.get(
            "최소 차트 점수",
            ""
        )

        csv_export_df["최대 결과 수"] = csv_search_conditions.get(
            "최대 결과 수",
            ""
        )

        csv_condition_summary = (
            f"시장 {csv_search_conditions.get('분석 시장', '')} · "
            f"시작 위치 {csv_search_conditions.get('분석 시작 위치', '')} · "
            f"분석 종목 수 {csv_search_conditions.get('분석 종목 수', '')}개 · "
            f"5일선 {csv_search_conditions.get('5일선 조건', '')} · "
            f"20일선 {csv_search_conditions.get('20일선 조건', '')} · "
            f"이동평균선 배열 {csv_search_conditions.get('이동평균선 배열 조건', '')} · "
            f"최소 거래량 {csv_search_conditions.get('최소 거래량 배수', '')}배 · "
            f"최소 차트 점수 {csv_search_conditions.get('최소 차트 점수', '')}점 · "
            f"최대 결과 {csv_search_conditions.get('최대 결과 수', '')}개"
        )

        csv_export_df["분석 조건 요약"] = csv_condition_summary

        csv_export_df = csv_export_df.rename(
            columns={
                "수급 반영 점수": "최종 추천 점수"
            }
        )

        csv_export_df["종목코드"] = (
            csv_export_df["종목코드"]
            .astype(str)
            .str.zfill(6)
            .apply(lambda code: f'="{code}"')
        )

        preferred_columns = [
            "종목명",
            "시장",
            "종목코드",
            "최근 종가",
            "차트 점수",
            "공시 점수",
            "종합 점수",
            "종합 등급",
            "수급 점수",
            "최종 추천 점수",
            "최종 추천 등급",
            "최종 추천 의견",
            "상태 요약",
            "상승 근거",
            "주의 사항",
            "실시간 차트",
            "5일선",
            "20일선",
            "거래량 배수",
            "분석 완료 시각",
            "분석 소요시간(초)",
            "전체 분석 수",
            "정상 처리 수",
            "조건 탈락 수",
            "오류 수",
            "추천 후보 수",
            "분석 시장",
            "분석 시작 위치",
            "분석 종목 수",
            "5일선 조건",
            "20일선 조건",
            "이동평균선 배열 조건",
            "최소 거래량 배수",
            "최소 차트 점수",
            "최대 결과 수",
            "분석 조건 요약"
        ]

        existing_preferred_columns = [
            column
            for column in preferred_columns
            if column in csv_export_df.columns
        ]

        remaining_columns = [
            column
            for column in csv_export_df.columns
            if column not in existing_preferred_columns
        ]

        csv_export_df = csv_export_df[
            existing_preferred_columns + remaining_columns
        ]

        csv_data = csv_export_df.to_csv(
            index=False,
            encoding="utf-8-sig"
        )
        download_date = datetime.now().strftime("%Y-%m-%d")

        st.download_button(
            label="추천 후보 결과 저장",
            data=csv_data,
            file_name=f"stock_candidates_{download_date}.csv",
            mime="text/csv",
            key="candidate_download"
        )

    if "candidate_results" in st.session_state:
        detail_df = st.session_state["candidate_results"]

        st.divider()
        st.subheader("추천 종목 상세 확인")

        selected_candidate = st.selectbox(
            "상세 확인할 종목을 선택하세요",
            detail_df["종목명"].tolist(),
            key="candidate_detail_select"
        )

        selected_row = detail_df[
            detail_df["종목명"] == selected_candidate
        ].iloc[0]

        col_a, col_b, col_c, col_d, col_e = st.columns(5)

        col_a.metric(
            "종목코드",
            str(selected_row["종목코드"]).zfill(6)
        )

        col_b.metric(
            "차트 점수",
            f"{selected_row['차트 점수']}점"
        )

        col_c.metric(
            "공시 점수",
            f"{selected_row['공시 점수']}점"
        )

        col_d.metric(
            "차트·공시 종합 점수",
            f"{selected_row['종합 점수']}점"
        )

        col_e.metric(
            "최종 추천 점수",
            f"{selected_row['수급 반영 점수']}점"
        )

        st.write(
            f"최종 추천 등급: **{selected_row['최종 추천 등급']}**"
        )

        final_grade = selected_row["최종 추천 등급"]
        final_score = selected_row["수급 반영 점수"]

        if final_grade == "A":
            final_opinion = "차트·공시·수급이 전반적으로 강한 최우선 검토 후보"
        elif final_grade == "B":
            final_opinion = "긍정 신호가 우세하지만 추가 확인이 필요한 후보"
        elif final_grade == "C":
            final_opinion = "일부 강점은 있으나 신중한 관찰이 필요한 후보"
        else:
            final_opinion = "현재 조건에서는 우선순위가 낮은 후보"

        st.write(
            f"최종 추천 의견: **{final_grade}등급 · "
            f"{final_score}점 · {final_opinion}**"
        )

        st.write(
            f"상태 요약: **{selected_row['상태 요약']}**"
        )

        investor_data = load_investor_trading(
            str(selected_row["종목코드"]).zfill(6)
        )

        st.subheader("외국인·기관·개인 수급")

        if investor_data["조회상태"] == "정상":
            st.caption(
                f"기준일: {investor_data['기준일']} · 단위: 억 원"
            )

            flow_col1, flow_col2, flow_col3 = st.columns(3)

            flow_col1.metric(
                "개인 최근 5일",
                f"{investor_data['개인_5일']:+,.1f}억"
            )

            flow_col2.metric(
                "기관 최근 5일",
                f"{investor_data['기관_5일']:+,.1f}억"
            )

            flow_col3.metric(
                "외국인 최근 5일",
                f"{investor_data['외국인_5일']:+,.1f}억"
            )

            flow_col4, flow_col5, flow_col6 = st.columns(3)

            flow_col4.metric(
                "개인 최근 10일",
                f"{investor_data['개인_10일']:+,.1f}억"
            )

            flow_col5.metric(
                "기관 최근 10일",
                f"{investor_data['기관_10일']:+,.1f}억"
            )

            flow_col6.metric(
                "외국인 최근 10일",
                f"{investor_data['외국인_10일']:+,.1f}억"
            )

            flow_score = calculate_flow_score(investor_data)

            flow_messages = []

            if investor_data["기관_5일"] > 0:
                flow_messages.append("기관 순매수")
            elif investor_data["기관_5일"] < 0:
                flow_messages.append("기관 순매도")

            if investor_data["외국인_5일"] > 0:
                flow_messages.append("외국인 순매수")
            elif investor_data["외국인_5일"] < 0:
                flow_messages.append("외국인 순매도")

            if (
                investor_data["기관_5일"] > 0
                and investor_data["외국인_5일"] > 0
            ):
                flow_messages.append("기관·외국인 동반 순매수")

            if (
                investor_data["기관_10일"] > 0
                and investor_data["외국인_10일"] > 0
            ):
                flow_messages.append("10일 누적 수급 양호")

            if not flow_messages:
                flow_messages.append("뚜렷한 수급 우위 없음")

            colored_messages = []

            for message in flow_messages:
                colored_message = (
                    message
                    .replace(
                        "순매수",
                        "<span style='color:#d32f2f; font-weight:700;'>순매수</span>"
                    )
                    .replace(
                        "순매도",
                        "<span style='color:#1976d2; font-weight:700;'>순매도</span>"
                    )
                )
                colored_messages.append(colored_message)

            st.markdown(
                """
                <div style="
                    padding: 14px 16px;
                    background-color: #e8f4ff;
                    border-radius: 8px;
                    color: #1f3b53;
                ">
                    <strong>수급 해석:</strong>
                    {}
                </div>
                """.format(" · ".join(colored_messages)),
                unsafe_allow_html=True
            )

            st.metric(
                "수급 점수",
                f"{flow_score}점"
            )

        else:
            st.warning(
                f"수급 데이터를 불러오지 못했습니다: "
                f"{investor_data['조회상태']}"
            )

        watchlist_file = "watchlist.csv"

        if st.button(
            "⭐ 관심종목에 추가",
            key="add_candidate_watchlist"
        ):
            selected_code = str(
                selected_row["종목코드"]
            ).zfill(6)

            new_watchlist_row = pd.DataFrame([{
                "종목명": selected_candidate,
                "시장": selected_row["시장"],
                "종목코드": selected_code,
                "차트 점수": selected_row["차트 점수"],
                "공시 점수": selected_row["공시 점수"],
                "종합 점수": selected_row["종합 점수"],
                "종합 등급": selected_row["종합 등급"],
                "상태 요약": selected_row["상태 요약"],
                "저장 날짜": datetime.today().strftime("%Y-%m-%d")
            }])

            if os.path.exists(watchlist_file):
                watchlist_df = pd.read_csv(
                    watchlist_file,
                    dtype={"종목코드": str}
                )
            else:
                watchlist_df = pd.DataFrame()

            if (
                not watchlist_df.empty
                and selected_code in
                watchlist_df["종목코드"].astype(str).str.zfill(6).values
            ):
                st.info("이미 관심종목에 저장된 종목입니다.")

            else:
                watchlist_df = pd.concat(
                    [watchlist_df, new_watchlist_row],
                    ignore_index=True
                )

                watchlist_df.to_csv(
                    watchlist_file,
                    index=False,
                    encoding="utf-8-sig"
                )

                st.success(
                    f"{selected_candidate}을 관심종목에 저장했습니다."
                )

        if st.button(
            "선택 종목 상세 차트 보기",
            key="candidate_detail_chart"
        ):
            try:
                selected_code = str(
                    selected_row["종목코드"]
                ).zfill(6)

                detail_start_date = (
                    datetime.today() - timedelta(days=180)
                )

                detail_data = fdr.DataReader(
                    selected_code,
                    detail_start_date.strftime("%Y-%m-%d")
                )

                if detail_data.empty:
                    st.warning("주가 데이터를 찾지 못했습니다.")

                else:
                    detail_data["5일선"] = (
                        detail_data["Close"].rolling(5).mean()
                    )

                    detail_data["20일선"] = (
                        detail_data["Close"].rolling(20).mean()
                    )

                    detail_chart = go.Figure()

                    detail_chart.add_trace(
                        go.Candlestick(
                            x=detail_data.index,
                            open=detail_data["Open"],
                            high=detail_data["High"],
                            low=detail_data["Low"],
                            close=detail_data["Close"],
                            name="주가"
                        )
                    )

                    detail_chart.add_trace(
                        go.Scatter(
                            x=detail_data.index,
                            y=detail_data["5일선"],
                            name="5일선"
                        )
                    )

                    detail_chart.add_trace(
                        go.Scatter(
                            x=detail_data.index,
                            y=detail_data["20일선"],
                            name="20일선"
                        )
                    )

                    detail_chart.update_layout(
                        title=f"{selected_candidate} 상세 차트",
                        xaxis_rangeslider_visible=False,
                        height=600
                    )

                    st.plotly_chart(
                        detail_chart,
                        width="stretch"
                    )

                    st.subheader(
                        f"{selected_candidate} 최근 30일 공시"
                    )

                    corp_codes = load_dart_corp_codes()

                    matched_corp = corp_codes[
                        corp_codes["stock_code"] == selected_code
                    ]

                    if matched_corp.empty:
                        st.warning(
                            "이 종목의 DART 회사코드를 찾지 못했습니다."
                        )

                    else:
                        corp_code = matched_corp.iloc[0]["corp_code"]

                        today = datetime.today()
                        disclosure_start = today - timedelta(days=30)

                        dart_url = (
                            "https://opendart.fss.or.kr/api/list.json"
                        )

                        dart_params = {
                            "crtfc_key": dart_api_key,
                            "corp_code": corp_code,
                            "bgn_de": disclosure_start.strftime("%Y%m%d"),
                            "end_de": today.strftime("%Y%m%d"),
                            "page_count": 100
                        }

                        dart_response = requests.get(
                            dart_url,
                            params=dart_params,
                            timeout=10
                        )

                        dart_result = dart_response.json()

                        if dart_result.get("status") == "000":
                            detail_disclosures = []

                            for item in dart_result["list"]:
                                title = item["report_nm"]

                                category, score, reason = (
                                    analyze_disclosure(title)
                                )

                                detail_disclosures.append({
                                    "공시 제목": title,
                                    "자동 분류": category,
                                    "공시 점수": score,
                                    "판단 근거": reason,
                                    "공시 날짜": item["rcept_dt"],
                                    "공시 원문": (
                                        "https://dart.fss.or.kr/"
                                        "dsaf001/main.do?"
                                        f"rcpNo={item['rcept_no']}"
                                    )
                                })

                            detail_disclosure_df = pd.DataFrame(
                                detail_disclosures
                            )

                            detail_disclosure_df = (
                                detail_disclosure_df.sort_values(
                                    by="공시 점수",
                                    ascending=False
                                )
                            )

                            st.success(
                                f"최근 30일 공시 "
                                f"{len(detail_disclosure_df)}건을 "
                                "찾았습니다."
                            )

                            st.dataframe(
                                detail_disclosure_df,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "공시 원문":
                                        st.column_config.LinkColumn(
                                            "공시 원문",
                                            display_text="원문 보기"
                                        )
                                }
                            )

                        elif dart_result.get("status") == "013":
                            st.info(
                                "최근 30일 동안 등록된 공시가 없습니다."
                            )

                        else:
                            st.error(
                                dart_result.get(
                                    "message",
                                    "공시 조회에 실패했습니다."
                                )
                            )


            except Exception as error:
                st.error(
                    f"상세 차트를 불러오지 못했습니다: {error}"
                )


# --------------------------------------------------
# 네 번째 탭: 관심종목
# --------------------------------------------------
with tab4:
    st.subheader("⭐ 관심종목 관리")

    watchlist_file = "watchlist.csv"

    if os.path.exists(watchlist_file):
        watchlist_df = pd.read_csv(
            watchlist_file,
            dtype={"종목코드": str}
        )

        if watchlist_df.empty:
            st.info("저장된 관심종목이 없습니다.")

        else:
            watchlist_df["종목코드"] = (
                watchlist_df["종목코드"]
                .astype(str)
                .str.zfill(6)
            )

            st.success(
                f"관심종목 {len(watchlist_df)}개가 저장되어 있습니다."
            )

            # ------------------------------------------
            # 기존 점수 중복 기록 정리
            # ------------------------------------------

            if "duplicate_clean_message" in st.session_state:
                st.success(
                    st.session_state.pop(
                        "duplicate_clean_message"
                    )
                )


            with st.expander(
                "🗂️ 점수 기록 및 백업 관리",
                expanded=False
            ):

                st.markdown("### 🧹 중복 기록 정리")

                st.write(
                    "같은 종목·같은 날짜에 차트, 공시, "
                    "종합 점수와 등급이 모두 같은 기록은 "
                    "가장 최근 기록 한 건만 남깁니다."
                )

                st.write(
                    "정리 전 원본은 별도의 백업 CSV 파일로 "
                    "자동 저장됩니다."
                )

                if st.button(
                    "🧹 중복 기록 정리 시작",
                    key="clean_duplicate_score_history"
                ):
                    try:
                        clean_result = (
                            clean_duplicate_score_history(
                                "watchlist_history.csv"
                            )
                        )

                        if clean_result["status"] == "cleaned":
                            st.success(
                                f"중복 기록 "
                                f"{clean_result['removed_count']}건을 "
                                "정리했습니다."
                            )

                            st.info(
                                f"백업 파일: "
                                f"{clean_result['backup_file']}"
                            )

                            st.session_state[
                                "duplicate_clean_message"
                            ] = (
                                f"중복 기록 "
                                f"{clean_result['removed_count']}건을 "
                                "정리했습니다."
                            )

                            st.rerun()

                        elif (
                            clean_result["status"]
                            == "no_duplicates"
                        ):
                            st.info(
                                "정리할 중복 기록이 없습니다."
                            )

                        elif clean_result["status"] == "no_file":
                            st.info(
                                "아직 점수 변동 기록 파일이 없습니다."
                            )

                        else:
                            st.info(
                                "점수 변동 기록 파일이 비어 있습니다."
                            )

                    except Exception as error:
                        st.error(
                            f"중복 기록 정리 오류: {error}"
                        )

                st.divider()

                st.markdown("### 💾 백업 파일 관리")

                st.write(
                    "최근 생성된 점수 기록 백업 파일로 "
                    "되돌릴 수 있습니다."
                )

                backup_files = [
                    file_name
                    for file_name in os.listdir(".")
                    if (
                        file_name.startswith(
                            "watchlist_history_backup_"
                        )
                        and file_name.endswith(".csv")
                    )
                ]

                backup_files = sorted(
                    backup_files,
                    reverse=True
                )

                if backup_files:
                    backup_rows = []

                    for backup_file_name in backup_files:
                        backup_file_time = os.path.getmtime(
                            backup_file_name
                        )

                        backup_rows.append({
                            "백업 파일명": backup_file_name,
                            "생성 시각": datetime.fromtimestamp(
                                backup_file_time
                            ).strftime("%Y-%m-%d %H:%M:%S")
                        })

                    backup_list_df = pd.DataFrame(
                        backup_rows
                    )

                    st.write(
                        f"현재 백업 파일: **{len(backup_list_df)}개**"
                    )

                    st.dataframe(
                        backup_list_df,
                        width="stretch",
                        hide_index=True
                    )

                    selected_backup_file = st.selectbox(
                        "복원할 백업 파일을 선택하세요",
                        options=backup_files,
                        index=0,
                        key="selected_score_history_backup"
                    )

                    with open(
                    selected_backup_file,
                        "rb"
                    ) as backup_download_file:
                        backup_download_data = (
                            backup_download_file.read()
                        )

                    st.download_button(
                        label="📥 선택한 백업 파일 다운로드",
                        data=backup_download_data,
                        file_name=selected_backup_file,
                        mime="text/csv",
                        key="download_selected_score_backup"
                    )

                    if st.button(
                        "♻️ 최근 백업 기록 복원",
                        key="restore_latest_score_backup"
                    ):
                        try:
                            backup_df = pd.read_csv(
                                selected_backup_file,
                                dtype={"종목코드": str}
                            )

                            backup_df.to_csv(
                                "watchlist_history.csv",
                                index=False,
                                encoding="utf-8-sig"
                            )

                            restore_result = {
                                "status": "restored",
                                "backup_file": selected_backup_file
                            }

                            if (
                                restore_result["status"]
                                == "restored"
                            ):
                                st.success(
                                    "점수 변동 기록을 다음 백업으로 "
                                    "복원했습니다: "
                                    f"{restore_result['backup_file']}"
                                )

                            else:
                                st.info(
                                    "복원할 점수 기록 백업 파일이 "
                                    "없습니다."
                                )

                        except Exception as error:
                            st.error(
                                f"백업 기록 복원 오류: {error}"
                            )

                    st.divider()

                    st.warning(
                        "백업 파일 삭제는 되돌릴 수 없습니다. "
                        "삭제할 파일을 정확히 확인하세요."
                    )

                    selected_delete_backup_file = st.selectbox(
                        "삭제할 백업 파일을 선택하세요",
                        options=backup_files,
                        index=0,
                        key="selected_delete_score_history_backup"
                    )

                    delete_backup_confirmed = st.checkbox(
                        "선택한 백업 파일을 삭제하는 것에 동의합니다.",
                        key="confirm_delete_score_history_backup"
                    )

                    if st.button(
                        "🗑️ 선택한 백업 파일 삭제",
                        key="delete_selected_score_history_backup"
                    ):

                        if not delete_backup_confirmed:
                            st.warning(
                                "백업 파일 삭제 동의 체크박스를 "
                                "먼저 선택해주세요."
                            )
                            st.stop()
                        try:
                            if os.path.exists(
                                selected_delete_backup_file
                            ):
                                os.remove(
                                    selected_delete_backup_file
                                )

                                st.success(
                                    "선택한 백업 파일을 "
                                    "삭제했습니다."
                                )

                                st.rerun()

                            else:
                                st.info(
                                    "선택한 백업 파일을 "
                                    "찾을 수 없습니다."
                                )

                        except Exception as error:
                            st.error(
                                f"백업 파일 삭제 오류: {error}"
                            )

                else:
                    st.info(
                        "현재 생성된 점수 기록 백업 파일이 없습니다. "
                        "중복 기록 정리를 실행해 실제 중복 기록이 "
                        "정리되면 백업 파일이 자동 생성됩니다."
                    )

                


            # ------------------------------------------
            # 관심종목 전체 요약 대시보드
            # ------------------------------------------
            with st.expander(
                "📌 관심종목 전체 요약",
                expanded=False
            ):

                watchlist_summary_df = watchlist_df.copy()

                watchlist_summary_df["차트 점수"] = pd.to_numeric(
                    watchlist_summary_df["차트 점수"],
                    errors="coerce"
                ).fillna(0)

                watchlist_summary_df["공시 점수"] = pd.to_numeric(
                    watchlist_summary_df["공시 점수"],
                    errors="coerce"
                ).fillna(0)

                watchlist_summary_df["종합 점수"] = pd.to_numeric(
                    watchlist_summary_df["종합 점수"],
                    errors="coerce"
                ).fillna(0)

                total_watchlist_count = len(
                    watchlist_summary_df
                )

                average_total_score = round(
                    watchlist_summary_df["종합 점수"].mean(),
                    1
                )

                grade_a_count = len(
                    watchlist_summary_df[
                        watchlist_summary_df["종합 등급"] == "A"
                    ]
                )

                caution_count = len(
                    watchlist_summary_df[
                        (
                            watchlist_summary_df["종합 등급"].isin(
                                ["C", "D"]
                            )
                        )
                        |
                        (
                            watchlist_summary_df["공시 점수"] < 40
                        )
                    ]
                )

                (
                    summary_col_1,
                    summary_col_2,
                    summary_col_3,
                    summary_col_4
                ) = st.columns(4)

                summary_col_1.metric(
                    "전체 관심종목",
                    f"{total_watchlist_count}개"
                )

                summary_col_2.metric(
                    "평균 종합 점수",
                    f"{average_total_score:.1f}점"
                )

                summary_col_3.metric(
                    "A등급 종목",
                    f"{grade_a_count}개"
                )

                summary_col_4.metric(
                    "주의 종목",
                    f"{caution_count}개"
                )

                if caution_count > 0:
                    st.warning(
                        f"현재 주의가 필요한 관심종목이 "
                        f"{caution_count}개 있습니다."
                    )

                else:
                    st.success(
                        "현재 C·D등급 또는 공시 점수 40점 미만인 "
                        "관심종목이 없습니다."
                    )

            # ------------------------------------------
            # 관심종목 종합점수 순위
            # ------------------------------------------
            with st.expander(
                "🏆 관심종목 종합점수 순위",
                expanded=False
            ):

                ranking_df = watchlist_summary_df.copy()

                ranking_df = ranking_df.sort_values(
                    by=[
                        "종합 점수",
                        "공시 점수",
                        "차트 점수"
                    ],
                    ascending=[
                        False,
                        False,
                        False
                    ]
                ).reset_index(drop=True)

                ranking_df.insert(
                    0,
                    "순위",
                    range(1, len(ranking_df) + 1)
                )

                def make_attention_status(row):
                    if (
                        row["종합 등급"] in ["C", "D"]
                        or row["공시 점수"] < 40
                    ):
                        return "⚠️ 주의"

                    if row["종합 등급"] == "A":
                        return "✅ 우수"

                    return "🔎 관찰"

                ranking_df["관리 상태"] = ranking_df.apply(
                    make_attention_status,
                    axis=1
                )

                ranking_display_df = ranking_df[[
                    "순위",
                    "종목명",
                    "시장",
                    "종목코드",
                    "차트 점수",
                    "공시 점수",
                    "종합 점수",
                    "종합 등급",
                    "관리 상태",
                    "상태 요약"
                ]].copy()

                ranking_display_df["종목코드"] = (
                    ranking_display_df["종목코드"]
                    .astype(str)
                    .str.zfill(6)
                )

                st.dataframe(
                    ranking_display_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "순위": st.column_config.NumberColumn(
                            "순위",
                            format="%d위"
                        ),
                        "차트 점수": st.column_config.ProgressColumn(
                            "차트 점수",
                            min_value=0,
                            max_value=100,
                            format="%d점"
                        ),
                        "공시 점수": st.column_config.ProgressColumn(
                            "공시 점수",
                            min_value=0,
                            max_value=100,
                            format="%d점"
                        ),
                        "종합 점수": st.column_config.ProgressColumn(
                            "종합 점수",
                            min_value=0,
                            max_value=100,
                            format="%d점"
                        )
                    }
                )  

            # ------------------------------------------
            # 관심종목 최근 점수 변화 요약
            # ------------------------------------------
            with st.expander(
                "🔄 관심종목 최근 점수 변화",
                expanded=False
            ):

                history_file = "watchlist_history.csv"

                if os.path.exists(history_file):
                    recent_history_df = pd.read_csv(
                        history_file,
                        dtype={"종목코드": str}
                    )

                    recent_history_df["종목코드"] = (
                        recent_history_df["종목코드"]
                        .astype(str)
                        .str.zfill(6)
                    )

                    recent_history_df["기록일시"] = pd.to_datetime(
                        recent_history_df["기록일시"],
                        errors="coerce"
                    )

                    recent_history_df = (
                        recent_history_df.dropna(
                            subset=["기록일시"]
                        )
                        .sort_values(
                            by="기록일시",
                            ascending=False
                        )
                    )

                    latest_change_df = (
                        recent_history_df.drop_duplicates(
                            subset=["종목코드"],
                            keep="first"
                        )
                        .copy()
                    )

                    latest_change_df["차트 점수 변화"] = pd.to_numeric(
                        latest_change_df["차트 점수 변화"],
                        errors="coerce"
                    ).fillna(0).astype(int)

                    latest_change_df["공시 점수 변화"] = pd.to_numeric(
                        latest_change_df["공시 점수 변화"],
                        errors="coerce"
                    ).fillna(0).astype(int)

                    latest_change_df["종합 점수 변화"] = pd.to_numeric(
                        latest_change_df["종합 점수 변화"],
                        errors="coerce"
                    ).fillna(0).astype(int)

                    def make_recent_change_status(row):
                        if row["종합 점수 변화"] <= -10:
                            return "🚨 급락 주의"

                        if (
                            row["공시 점수 변화"] <= -15
                            or row["차트 점수 변화"] <= -15
                        ):
                            return "⚠️ 하락 주의"

                        if row["종합 점수 변화"] < 0:
                            return "🔻 소폭 하락"

                        if row["종합 점수 변화"] >= 10:
                            return "🚀 큰 폭 상승"

                        if (
                            row["공시 점수 변화"] > 0
                            or row["차트 점수 변화"] > 0
                            or row["종합 점수 변화"] > 0
                        ):
                            return "🔺 상승"

                        return "➖ 변화 없음"

                    latest_change_df["변화 상태"] = (
                        latest_change_df.apply(
                            make_recent_change_status,
                            axis=1
                        )
                    )

                    latest_change_df["등급 변화"] = (
                        latest_change_df["이전 등급"].astype(str)
                        + " → "
                        + latest_change_df["현재 등급"].astype(str)
                    )

                    latest_change_df["최근 갱신"] = (
                        latest_change_df["기록일시"]
                        .dt.strftime("%Y-%m-%d %H:%M:%S")
                    )

                    watchlist_code_df = watchlist_summary_df[[
                        "종목명",
                        "종목코드"
                    ]].copy()

                    watchlist_code_df["종목코드"] = (
                        watchlist_code_df["종목코드"]
                        .astype(str)
                        .str.zfill(6)
                    )

                    recent_change_display_df = watchlist_code_df.merge(
                        latest_change_df[[
                            "종목코드",
                            "차트 점수 변화",
                            "공시 점수 변화",
                            "종합 점수 변화",
                            "등급 변화",
                            "변화 상태",
                            "최근 갱신"
                        ]],
                        on="종목코드",
                        how="left"
                    )

                    recent_change_display_df[
                        "차트 점수 변화"
                    ] = recent_change_display_df[
                        "차트 점수 변화"
                    ].fillna(0).astype(int)

                    recent_change_display_df[
                        "공시 점수 변화"
                    ] = recent_change_display_df[
                        "공시 점수 변화"
                    ].fillna(0).astype(int)

                    recent_change_display_df[
                        "종합 점수 변화"
                    ] = recent_change_display_df[
                        "종합 점수 변화"
                    ].fillna(0).astype(int)

                    recent_change_display_df[
                        "등급 변화"
                    ] = recent_change_display_df[
                        "등급 변화"
                    ].fillna("-")

                    recent_change_display_df[
                        "변화 상태"
                    ] = recent_change_display_df[
                        "변화 상태"
                    ].fillna("기록 없음")

                    recent_change_display_df[
                        "최근 갱신"
                    ] = recent_change_display_df[
                        "최근 갱신"
                    ].fillna("-")

                    recent_change_display_df = (
                        recent_change_display_df.sort_values(
                            by="종합 점수 변화",
                            ascending=True
                        )
                    )

                    # ------------------------------------------
                    # 최근 점수 변화 현황 요약 카드
                    # ------------------------------------------
                    rising_count = len(
                        recent_change_display_df[
                            recent_change_display_df[
                                "종합 점수 변화"
                            ] > 0
                        ]
                    )

                    falling_count = len(
                        recent_change_display_df[
                            recent_change_display_df[
                                "종합 점수 변화"
                            ] < 0
                        ]
                    )

                    urgent_count = len(
                        recent_change_display_df[
                            recent_change_display_df[
                                "변화 상태"
                            ].isin(
                                [
                                    "🚨 급락 주의",
                                    "⚠️ 하락 주의"
                                ]
                            )
                        ]
                    )

                    unchanged_count = len(
                        recent_change_display_df[
                            recent_change_display_df[
                                "변화 상태"
                            ] == "➖ 변화 없음"
                        ]
                    )

                    (
                        change_col_1,
                        change_col_2,
                        change_col_3,
                        change_col_4
                    ) = st.columns(4)

                    change_col_1.metric(
                        "상승 종목",
                        f"{rising_count}개"
                    )

                    change_col_2.metric(
                        "하락 종목",
                        f"{falling_count}개"
                    )

                    change_col_3.metric(
                        "급락·주의",
                        f"{urgent_count}개"
                    )

                    change_col_4.metric(
                        "변화 없음",
                        f"{unchanged_count}개"
                    )

                    if urgent_count > 0:
                        st.error(
                            f"최근 급락 또는 주의 변화가 감지된 종목이 "
                            f"{urgent_count}개 있습니다."
                        )

                    elif falling_count > 0:
                        st.warning(
                            f"최근 점수가 하락한 관심종목이 "
                            f"{falling_count}개 있습니다."
                        )

                    elif rising_count > 0:
                        st.success(
                            f"최근 점수가 상승한 관심종목이 "
                            f"{rising_count}개 있습니다."
                        )

                    else:
                        st.info(
                            "최근 갱신에서 큰 점수 변화가 없습니다."
                        )

                    # ------------------------------------------
                    # 최근 점수 변화 필터
                    # ------------------------------------------
                    change_filter = st.selectbox(
                        "최근 점수 변화 필터",
                        [
                            "전체",
                            "상승 종목",
                            "하락 종목",
                            "급락·주의 종목",
                            "변화 없는 종목"
                        ],
                        key="recent_change_filter"
                    )

                    filtered_change_df = (
                        recent_change_display_df.copy()
                    )

                    if change_filter == "상승 종목":
                        filtered_change_df = filtered_change_df[
                            filtered_change_df["종합 점수 변화"] > 0
                        ]

                    elif change_filter == "하락 종목":
                        filtered_change_df = filtered_change_df[
                            filtered_change_df["종합 점수 변화"] < 0
                        ]

                    elif change_filter == "급락·주의 종목":
                        filtered_change_df = filtered_change_df[
                            filtered_change_df["변화 상태"].isin(
                                [
                                    "🚨 급락 주의",
                                    "⚠️ 하락 주의"
                                ]
                            )
                        ]

                    elif change_filter == "변화 없는 종목":
                        filtered_change_df = filtered_change_df[
                            filtered_change_df["변화 상태"]
                            == "➖ 변화 없음"
                        ]

                    st.caption(
                        f"선택 조건에 해당하는 종목: "
                        f"{len(filtered_change_df)}개"
                    )

                    if filtered_change_df.empty:
                        st.info(
                            "선택한 조건에 해당하는 관심종목이 없습니다."
                        )

                    st.dataframe(
                        filtered_change_df,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "차트 점수 변화":
                                st.column_config.NumberColumn(
                                    "차트 변화",
                                    format="%+d점"
                                ),
                            "공시 점수 변화":
                                st.column_config.NumberColumn(
                                    "공시 변화",
                                    format="%+d점"
                                ),
                            "종합 점수 변화":
                                st.column_config.NumberColumn(
                                    "종합 변화",
                                    format="%+d점"
                                )
                        }
                    )

                    # ------------------------------------------
                    # 관심종목 분석 결과 CSV 다운로드
                    # ------------------------------------------
                    st.subheader("💾 관심종목 분석 결과 저장")

                    download_col_1, download_col_2 = st.columns(2)

                    ranking_csv_data = ranking_display_df.to_csv(
                        index=False,
                        encoding="utf-8-sig"
                    )

                    download_col_1.download_button(
                        label="📥 관심종목 순위 저장",
                        data=ranking_csv_data,
                        file_name=(
                            "watchlist_ranking_"
                            + datetime.today().strftime("%Y%m%d")
                            + ".csv"
                        ),
                        mime="text/csv",
                        key="download_watchlist_ranking"
                    )

                    change_csv_data = filtered_change_df.to_csv(
                        index=False,
                        encoding="utf-8-sig"
                    )

                    download_col_2.download_button(
                        label="📥 최근 점수 변화 저장",
                        data=change_csv_data,
                        file_name=(
                            "watchlist_score_changes_"
                            + datetime.today().strftime("%Y%m%d")
                            + ".csv"
                        ),
                        mime="text/csv",
                        key="download_watchlist_changes"
                    )

                    st.caption(
                        "현재 화면에 표시된 필터 결과가 CSV 파일로 "
                        "저장됩니다."
                    )

                    # ------------------------------------------
                    # 전체 관심종목 종합점수 추이 비교
                    # ------------------------------------------
                    st.subheader("📈 전체 관심종목 종합점수 추이")

                    total_trend_df = recent_history_df.copy()

                    total_trend_df["현재 종합 점수"] = pd.to_numeric(
                        total_trend_df["현재 종합 점수"],
                        errors="coerce"
                    )

                    current_watchlist_codes = (
                        watchlist_summary_df["종목코드"]
                        .astype(str)
                        .str.zfill(6)
                        .tolist()
                    )

                    total_trend_df = total_trend_df[
                        total_trend_df["종목코드"].isin(
                            current_watchlist_codes
                        )
                    ].copy()

                    total_trend_df = total_trend_df.dropna(
                        subset=[
                            "기록일시",
                            "현재 종합 점수"
                        ]
                    )

                    total_trend_df = total_trend_df.sort_values(
                        by="기록일시",
                        ascending=True
                    )

                    available_trend_stocks = sorted(
                        total_trend_df["종목명"]
                        .dropna()
                        .astype(str)
                        .unique()
                        .tolist()
                    )

                    selected_trend_stocks = st.multiselect(
                        "그래프에서 비교할 관심종목",
                        options=available_trend_stocks,
                        default=available_trend_stocks,
                        key="watchlist_total_trend_select"
                    )

                    trend_period = st.selectbox(
                        "그래프 조회 기간",
                        [
                            "전체 기간",
                            "최근 7일",
                            "최근 30일",
                            "최근 90일"
                        ],
                        index=0,
                        key="watchlist_total_trend_period"
                    )

                    period_trend_df = total_trend_df.copy()

                    if trend_period != "전체 기간":
                        period_days = {
                            "최근 7일": 7,
                            "최근 30일": 30,
                            "최근 90일": 90
                        }[trend_period]

                        period_start_date = (
                            datetime.today()
                            - timedelta(days=period_days)
                        )

                        period_trend_df = period_trend_df[
                            period_trend_df["기록일시"]
                            >= period_start_date
                        ].copy()

                    filtered_trend_df = period_trend_df[
                        period_trend_df["종목명"].isin(
                            selected_trend_stocks
                        )
                    ].copy()

                    if filtered_trend_df.empty:
                        st.info(
                            "그래프에 표시할 종목이나 "
                            "점수 변동 기록이 없습니다."
                        )

                    else:
                        watchlist_total_chart = go.Figure()

                        for trend_stock_name in selected_trend_stocks:
                            stock_trend_df = filtered_trend_df[
                                filtered_trend_df["종목명"]
                                == trend_stock_name
                            ].copy()

                            stock_trend_df = stock_trend_df.sort_values(
                                by="기록일시",
                                ascending=True
                            )

                            watchlist_total_chart.add_trace(
                                go.Scatter(
                                    x=stock_trend_df["기록일시"],
                                    y=stock_trend_df[
                                        "현재 종합 점수"
                                    ],
                                    mode="lines+markers",
                                    name=trend_stock_name
                                )
                            )

                        watchlist_total_chart.update_layout(
                            title=(
                                f"관심종목 종합점수 변화 비교 "
                                f"({trend_period})"
                            ),
                            xaxis_title="갱신 일시",
                            yaxis_title="종합 점수",
                            yaxis={
                                "range": [0, 100],
                                "dtick": 10
                            },
                            hovermode="x unified",
                            height=500,
                            legend={
                                "orientation": "h",
                                "yanchor": "bottom",
                                "y": 1.02,
                                "xanchor": "right",
                                "x": 1
                            }
                        )

                        watchlist_total_chart.update_xaxes(
                            tickformat="%m-%d\n%H:%M"
                        )

                        st.plotly_chart(
                            watchlist_total_chart,
                            width="stretch"
                        )

                        # ------------------------------------------
                        # 선택 기간 종합점수 변화 요약
                        # ------------------------------------------
                        st.subheader("📋 선택 기간 종합점수 요약")

                        period_summary_rows = []

                        for summary_stock_name in selected_trend_stocks:
                            summary_stock_df = filtered_trend_df[
                                filtered_trend_df["종목명"]
                                == summary_stock_name
                            ].copy()

                            summary_stock_df = (
                                summary_stock_df.sort_values(
                                    by="기록일시",
                                    ascending=True
                                )
                            )

                            if summary_stock_df.empty:
                                continue

                            start_score = int(
                                summary_stock_df.iloc[0][
                                    "현재 종합 점수"
                                ]
                            )

                            latest_score = int(
                                summary_stock_df.iloc[-1][
                                    "현재 종합 점수"
                                ]
                            )

                            score_change = latest_score - start_score

                            highest_score = int(
                                summary_stock_df[
                                    "현재 종합 점수"
                                ].max()
                            )

                            lowest_score = int(
                                summary_stock_df[
                                    "현재 종합 점수"
                                ].min()
                            )

                            record_count = len(summary_stock_df)

                            if score_change > 0:
                                trend_status = "🔺 상승"

                            elif score_change < 0:
                                trend_status = "🔻 하락"

                            else:
                                trend_status = "➖ 변화 없음"

                            period_summary_rows.append({
                                "종목명": summary_stock_name,
                                "기간 시작 점수": start_score,
                                "최근 점수": latest_score,
                                "기간 점수 변화": score_change,
                                "기간 최고 점수": highest_score,
                                "기간 최저 점수": lowest_score,
                                "기록 수": record_count,
                                "기간 흐름": trend_status
                            })

                        if period_summary_rows:
                            period_summary_df = pd.DataFrame(
                                period_summary_rows
                            )

                            period_summary_df = (
                                period_summary_df.sort_values(
                                    by="기간 점수 변화",
                                    ascending=False
                                )
                            )

                            st.dataframe(
                                period_summary_df,
                                width="stretch",
                                hide_index=True,
                                column_config={
                                    "기간 시작 점수":
                                        st.column_config.NumberColumn(
                                            "시작 점수",
                                            format="%d점"
                                        ),
                                    "최근 점수":
                                        st.column_config.NumberColumn(
                                            "최근 점수",
                                            format="%d점"
                                        ),
                                    "기간 점수 변화":
                                        st.column_config.NumberColumn(
                                            "점수 변화",
                                            format="%+d점"
                                        ),
                                    "기간 최고 점수":
                                        st.column_config.NumberColumn(
                                            "최고 점수",
                                            format="%d점"
                                        ),
                                    "기간 최저 점수":
                                        st.column_config.NumberColumn(
                                            "최저 점수",
                                            format="%d점"
                                        ),
                                    "기록 수":
                                        st.column_config.NumberColumn(
                                            "기록 수",
                                            format="%d회"
                                        )
                                }
                            )

                        st.caption(
                            "전체 관심종목 점수 갱신을 반복하면 "
                            "종목별 종합점수 흐름이 누적 표시됩니다."
                        )

                else:
                    st.info(
                        "아직 점수 변동 기록이 없습니다. "
                        "전체 관심종목 점수 갱신 버튼을 눌러주세요."
                    )

                st.divider()

            # ------------------------------------------
            # 전체 관심종목 점수 일괄 갱신
            # ------------------------------------------

            with st.expander(
                "🔄 전체 관심종목 점수 갱신",
                expanded=False
            ):

                if st.button(
                    "🔄 전체 관심종목 점수 갱신",
                    key="refresh_all_watchlist_stocks"
                ):
                    updated_watchlist_df = watchlist_df.copy()
                    history_file = "watchlist_history.csv"
                    history_rows = []
                    failed_stocks = []

                    refresh_time = datetime.today().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    total_stock_count = len(updated_watchlist_df)

                    for progress_index, (
                        row_index,
                        watchlist_row
                    ) in enumerate(updated_watchlist_df.iterrows()):
                        current_stock_name = str(
                            watchlist_row["종목명"]
                        )

                        current_stock_code = str(
                            watchlist_row["종목코드"]
                        ).zfill(6)

                        status_text.write(
                            f"갱신 중: {current_stock_name} "
                            f"({progress_index + 1}/{total_stock_count})"
                        )

                        try:
                            previous_chart_score = int(
                                float(watchlist_row["차트 점수"])
                            )

                            previous_disclosure_score = int(
                                float(watchlist_row["공시 점수"])
                            )

                            previous_total_score = int(
                                float(watchlist_row["종합 점수"])
                            )

                            previous_grade = str(
                                watchlist_row["종합 등급"]
                            )

                            refreshed_result = (
                                calculate_watchlist_scores(
                                    current_stock_code
                                )
                            )

                            refreshed_chart_score = int(
                                refreshed_result["차트 점수"]
                            )

                            refreshed_disclosure_score = int(
                                refreshed_result["공시 점수"]
                            )

                            refreshed_total_score = int(
                                refreshed_result["종합 점수"]
                            )

                            refreshed_grade = str(
                                refreshed_result["종합 등급"]
                            )

                            refreshed_status = str(
                                refreshed_result["상태 요약"]
                            )

                            updated_watchlist_df.loc[
                                row_index,
                                "차트 점수"
                            ] = refreshed_chart_score

                            updated_watchlist_df.loc[
                                row_index,
                                "공시 점수"
                            ] = refreshed_disclosure_score

                            updated_watchlist_df.loc[
                                row_index,
                                "종합 점수"
                            ] = refreshed_total_score

                            updated_watchlist_df.loc[
                                row_index,
                                "종합 등급"
                            ] = refreshed_grade

                            updated_watchlist_df.loc[
                                row_index,
                                "상태 요약"
                            ] = refreshed_status

                            updated_watchlist_df.loc[
                                row_index,
                                "저장 날짜"
                            ] = datetime.today().strftime("%Y-%m-%d")

                            history_record = {
                                "종목명": current_stock_name,
                                "종목코드": current_stock_code,
                                "기록일시": refresh_time,
                                "이전 차트 점수": previous_chart_score,
                                "현재 차트 점수": refreshed_chart_score,
                                "차트 점수 변화": (
                                    refreshed_chart_score
                                    - previous_chart_score
                                ),
                                "이전 공시 점수":
                                    previous_disclosure_score,
                                "현재 공시 점수":
                                    refreshed_disclosure_score,
                                "공시 점수 변화": (
                                    refreshed_disclosure_score
                                    - previous_disclosure_score
                                ),
                                "이전 종합 점수": previous_total_score,
                                "현재 종합 점수": refreshed_total_score,
                                "종합 점수 변화": (
                                    refreshed_total_score
                                    - previous_total_score
                                ),
                                "이전 등급": previous_grade,
                                "현재 등급": refreshed_grade
                            }

                            if should_save_score_history(
                                history_file,
                                history_record
                            ):
                                history_rows.append(
                                    history_record
                                )

                        except Exception as error:
                            failed_stocks.append(
                                f"{current_stock_name}: {error}"
                            )

                        progress_bar.progress(
                            int(
                                (
                                    (progress_index + 1)
                                    / total_stock_count
                                )
                                * 100
                            )
                        )

                    status_text.empty()
                    progress_bar.empty()

                    updated_watchlist_df.to_csv(
                        watchlist_file,
                        index=False,
                        encoding="utf-8-sig"
                    )

                    watchlist_df = updated_watchlist_df

                    if history_rows:
                        new_history_df = pd.DataFrame(
                            history_rows
                        )

                        if os.path.exists(history_file):
                            existing_history_df = pd.read_csv(
                                history_file,
                                dtype={"종목코드": str}
                            )

                            combined_history_df = pd.concat(
                                [
                                    existing_history_df,
                                    new_history_df
                                ],
                                ignore_index=True
                            )

                        else:
                            combined_history_df = new_history_df

                        combined_history_df.to_csv(
                            history_file,
                            index=False,
                            encoding="utf-8-sig"
                        )

                    watchlist_df = updated_watchlist_df

                    st.success(
                        f"관심종목 {total_stock_count}개의 "
                        "현재 점수 갱신을 완료했습니다."
                    )

                    if history_rows:
                        st.info(
                            f"새로운 점수 기록 {len(history_rows)}건을 "
                            "저장했습니다."
                        )

                    else:
                        st.info(
                            "오늘 저장된 최근 기록과 점수가 같아 "
                            "새로운 변동 기록은 추가하지 않았습니다."
                        )

                    if failed_stocks:
                        st.warning(
                            f"{len(failed_stocks)}개 종목은 "
                            "갱신하지 못했습니다."
                        )

                        with st.expander(
                            "갱신 실패 종목 확인"
                        ):
                            for failed_stock in failed_stocks:
                                st.write(f"- {failed_stock}")
            with st.expander(
                "📋 관심종목 목록 및 종목 선택",
                expanded=False
            ):                    
                st.dataframe(
                    watchlist_df,
                    width="stretch",
                    hide_index=True
                )

                selected_watchlist_stock = st.selectbox(
                    "확인할 관심종목을 선택하세요",
                    watchlist_df["종목명"].tolist(),
                    key="watchlist_delete_select"
                )

            # ------------------------------------------
            # 선택 관심종목 점수 변동 기록 표시
            # ------------------------------------------
            history_file = "watchlist_history.csv"

            with st.expander(
                f"📊 {selected_watchlist_stock} 점수 변동 기록",
                expanded=False
            ):

                if os.path.exists(history_file):
                    history_df = pd.read_csv(
                        history_file,
                        dtype={"종목코드": str}
                    )

                else:
                    history_df = pd.DataFrame(
                        columns=[
                            "종목명",
                            "종목코드",
                            "기록일시",
                            "이전 차트 점수",
                            "현재 차트 점수",
                            "차트 점수 변화",
                            "이전 공시 점수",
                            "현재 공시 점수",
                            "공시 점수 변화",
                            "이전 종합 점수",
                            "현재 종합 점수",
                            "종합 점수 변화",
                            "이전 등급",
                            "현재 등급"
                        ]
                    )

                history_df["종목코드"] = (
                    history_df["종목코드"]
                    .astype(str)
                    .str.zfill(6)
                )

                selected_history_df = history_df[
                    history_df["종목명"]
                    == selected_watchlist_stock
                ].copy()

                if selected_history_df.empty:
                    st.info(
                        "아직 이 종목의 점수 변동 기록이 없습니다. "
                        "점수 갱신 버튼을 한 번 눌러주세요."
                    )

                else:
                    selected_history_df = (
                        selected_history_df.sort_values(
                            by="기록일시",
                            ascending=False
                        )
                    )

                    latest_history = selected_history_df.iloc[0]

                    chart_change = int(
                        latest_history["차트 점수 변화"]
                    )

                    disclosure_change = int(
                        latest_history["공시 점수 변화"]
                    )

                    total_change = int(
                        latest_history["종합 점수 변화"]
                    )

                    col_history_1, col_history_2, col_history_3 = (
                        st.columns(3)
                    )

                    col_history_1.metric(
                        "차트 점수",
                        f"{int(latest_history['현재 차트 점수'])}점",
                        delta=f"{chart_change:+d}점"
                    )

                    col_history_2.metric(
                        "공시 점수",
                        f"{int(latest_history['현재 공시 점수'])}점",
                        delta=f"{disclosure_change:+d}점"
                    )

                    col_history_3.metric(
                        "종합 점수",
                        f"{int(latest_history['현재 종합 점수'])}점",
                        delta=f"{total_change:+d}점"
                    )

                    previous_grade = str(
                        latest_history["이전 등급"]
                    )

                    current_grade = str(
                        latest_history["현재 등급"]
                    )

                    st.write(
                        f"등급 변화: **{previous_grade} → "
                        f"{current_grade}**"
                    )

                    st.write(
                        f"최근 갱신 일시: "
                        f"**{latest_history['기록일시']}**"
                    )

                    if total_change > 0:
                        st.success(
                            f"종합 점수가 이전보다 "
                            f"{total_change}점 상승했습니다."
                        )

                    elif total_change < 0:
                        st.warning(
                            f"종합 점수가 이전보다 "
                            f"{abs(total_change)}점 하락했습니다."
                        )

                    else:
                        st.info(
                            "이전 갱신과 비교해 종합 점수 변화가 없습니다."
                        )

                    # ------------------------------------------
                    # 점수 급변 및 등급 변화 자동 경고
                    # ------------------------------------------
                    st.subheader("🚨 자동 변화 감지")

                    grade_order = {
                        "A": 4,
                        "B": 3,
                        "C": 2,
                        "D": 1
                    }

                    previous_grade_value = grade_order.get(
                        previous_grade,
                        0
                    )

                    current_grade_value = grade_order.get(
                        current_grade,
                        0
                    )

                    warning_detected = False
                    positive_detected = False

                    if total_change <= -10:
                        st.error(
                            f"종합 점수가 이전보다 "
                            f"{abs(total_change)}점 급락했습니다. "
                            "차트와 최근 공시 원문을 함께 확인하세요."
                        )
                        warning_detected = True

                    if disclosure_change <= -15:
                        st.error(
                            f"공시 점수가 이전보다 "
                            f"{abs(disclosure_change)}점 하락했습니다. "
                            "위험 공시 또는 새로운 부정 공시가 "
                            "등록됐는지 확인이 필요합니다."
                        )
                        warning_detected = True

                    if chart_change <= -15:
                        st.warning(
                            f"차트 점수가 이전보다 "
                            f"{abs(chart_change)}점 하락했습니다. "
                            "단기 주가 흐름과 거래량이 "
                            "약해졌을 가능성이 있습니다."
                        )
                        warning_detected = True

                    if current_grade_value < previous_grade_value:
                        st.error(
                            f"종합 등급이 {previous_grade}등급에서 "
                            f"{current_grade}등급으로 하락했습니다."
                        )
                        warning_detected = True

                    if total_change >= 10:
                        st.success(
                            f"종합 점수가 이전보다 "
                            f"{total_change}점 크게 상승했습니다."
                        )
                        positive_detected = True

                    if disclosure_change >= 15:
                        st.success(
                            f"공시 점수가 이전보다 "
                            f"{disclosure_change}점 상승했습니다. "
                            "새로운 긍정 공시가 반영됐을 "
                            "가능성이 있습니다."
                        )
                        positive_detected = True

                    if chart_change >= 15:
                        st.success(
                            f"차트 점수가 이전보다 "
                            f"{chart_change}점 상승했습니다. "
                            "차트 흐름이 강해졌습니다."
                        )
                        positive_detected = True

                    if current_grade_value > previous_grade_value:
                        st.success(
                            f"종합 등급이 {previous_grade}등급에서 "
                            f"{current_grade}등급으로 상승했습니다."
                        )
                        positive_detected = True

                    if not warning_detected and not positive_detected:
                        st.info(
                            "현재 점수와 등급에서 큰 변화가 "
                            "감지되지 않았습니다."
                        )    

                    # ------------------------------------------
                    # 관심종목 점수 변동 추이 그래프
                    # ------------------------------------------
                    chart_history_df = selected_history_df.copy()

                    chart_history_df["기록일시"] = pd.to_datetime(
                        chart_history_df["기록일시"],
                        errors="coerce"
                    )

                    chart_history_df = (
                        chart_history_df.dropna(
                            subset=["기록일시"]
                        )
                        .sort_values(
                            by="기록일시",
                            ascending=True
                        )
                    )

                    if not chart_history_df.empty:
                        st.subheader("📈 점수 변동 추이")

                        score_history_chart = go.Figure()

                        score_history_chart.add_trace(
                            go.Scatter(
                                x=chart_history_df["기록일시"],
                                y=chart_history_df[
                                    "현재 차트 점수"
                                ],
                                mode="lines+markers",
                                name="차트 점수"
                            )
                        )

                        score_history_chart.add_trace(
                            go.Scatter(
                                x=chart_history_df["기록일시"],
                                y=chart_history_df[
                                    "현재 공시 점수"
                                ],
                                mode="lines+markers",
                                name="공시 점수"
                            )
                        )

                        score_history_chart.add_trace(
                            go.Scatter(
                                x=chart_history_df["기록일시"],
                                y=chart_history_df[
                                    "현재 종합 점수"
                                ],
                                mode="lines+markers",
                                name="종합 점수"
                            )
                        )

                        score_history_chart.update_layout(
                            title=(
                                f"{selected_watchlist_stock} "
                                "점수 변동 추이"
                            ),
                            xaxis_title="갱신 일시",
                            yaxis_title="점수",
                            yaxis={
                                "range": [0, 100],
                                "dtick": 10
                            },
                            hovermode="x unified",
                            height=450,
                            legend={
                                "orientation": "h",
                                "yanchor": "bottom",
                                "y": 1.02,
                                "xanchor": "right",
                                "x": 1
                            }
                        )

                        score_history_chart.update_xaxes(
                            tickformat="%m-%d\n%H:%M"
                        )

                        st.plotly_chart(
                            score_history_chart,
                            width="stretch"
                        )

                    display_history_df = selected_history_df[[
                        "기록일시",
                        "이전 차트 점수",
                        "현재 차트 점수",
                        "차트 점수 변화",
                        "이전 공시 점수",
                        "현재 공시 점수",
                        "공시 점수 변화",
                        "이전 종합 점수",
                        "현재 종합 점수",
                        "종합 점수 변화",
                        "이전 등급",
                        "현재 등급"
                    ]]

                    st.dataframe(
                        display_history_df,
                        width="stretch",
                        hide_index=True
                    )

            if not os.path.exists(history_file):
                st.info(
                    "아직 점수 변동 기록 파일이 없습니다. "
                    "관심종목 점수 갱신 버튼을 눌러주세요."
                )
            if "individual_refresh_message" in st.session_state:
                st.success(
                    st.session_state.pop(
                        "individual_refresh_message"
                    )
                )

            if "individual_refresh_info" in st.session_state:
                st.info(
                    st.session_state.pop(
                        "individual_refresh_info"
                    )
                )
            with st.expander(
                "🛠️ 선택 종목 분석 및 차트",
                expanded=False
            ):
                if st.button(
                    "선택 종목 차트·공시 점수 갱신",
                    key="refresh_watchlist_stock"
                ):
                    selected_watchlist_row = watchlist_df[
                        watchlist_df["종목명"] == selected_watchlist_stock
                    ].iloc[0]

                    selected_watchlist_code = str(
                        selected_watchlist_row["종목코드"]
                    ).zfill(6)

                    try:
                        refresh_start_date = (
                            datetime.today() - timedelta(days=90)
                        )

                        refresh_data = fdr.DataReader(
                            selected_watchlist_code,
                            refresh_start_date.strftime("%Y-%m-%d")
                        )

                        if len(refresh_data) < 20:
                            st.warning(
                                "현재 점수를 계산할 주가 데이터가 부족합니다."
                            )

                        else:
                            refresh_data["5일선"] = (
                                refresh_data["Close"].rolling(5).mean()
                            )

                            refresh_data["20일선"] = (
                                refresh_data["Close"].rolling(20).mean()
                            )

                            refresh_data["20일평균거래량"] = (
                                refresh_data["Volume"].rolling(20).mean()
                            )

                            latest = refresh_data.iloc[-1]

                            current_price = latest["Close"]
                            ma5 = latest["5일선"]
                            ma20 = latest["20일선"]
                            current_volume = latest["Volume"]
                            average_volume = latest["20일평균거래량"]

                            if average_volume > 0:
                                volume_ratio = (
                                    current_volume / average_volume
                                )
                            else:
                                volume_ratio = 0

                            refreshed_chart_score = 50

                            if current_price > ma5:
                                refreshed_chart_score += 10
                            else:
                                refreshed_chart_score -= 10

                            if current_price > ma20:
                                refreshed_chart_score += 15
                            else:
                                refreshed_chart_score -= 15

                            if ma5 > ma20:
                                refreshed_chart_score += 15
                            else:
                                refreshed_chart_score -= 15

                            if volume_ratio >= 2:
                                refreshed_chart_score += 20
                            elif volume_ratio >= 1:
                                refreshed_chart_score += 10
                            else:
                                refreshed_chart_score -= 5

                            refreshed_chart_score = max(
                                0,
                                min(100, refreshed_chart_score)
                            )

                            refreshed_disclosure_score = 50

                            corp_codes = load_dart_corp_codes()

                            matched_corp = corp_codes[
                                corp_codes["stock_code"]
                                == selected_watchlist_code
                            ]

                            if not matched_corp.empty:
                                corp_code = matched_corp.iloc[0]["corp_code"]

                                today = datetime.today()
                                disclosure_start = (
                                    today - timedelta(days=30)
                                )

                                dart_url = (
                                    "https://opendart.fss.or.kr/"
                                    "api/list.json"
                                )

                                dart_params = {
                                    "crtfc_key": dart_api_key,
                                    "corp_code": corp_code,
                                    "bgn_de": disclosure_start.strftime(
                                        "%Y%m%d"
                                    ),
                                    "end_de": today.strftime("%Y%m%d"),
                                    "page_count": 100
                                }

                                dart_response = requests.get(
                                    dart_url,
                                    params=dart_params,
                                    timeout=10
                                )

                                dart_result = dart_response.json()

                                if dart_result.get("status") == "000":
                                    positive_scores = []
                                    risk_count = 0

                                    for item in dart_result["list"]:
                                        category, score, _ = (
                                            analyze_disclosure(
                                                item["report_nm"]
                                            )
                                        )

                                        if category == "긍정 후보":
                                            positive_scores.append(score)

                                        if category == "위험 확인":
                                            risk_count += 1

                                    if positive_scores:
                                        refreshed_disclosure_score = max(
                                            positive_scores
                                        )

                                    refreshed_disclosure_score -= (
                                        risk_count * 15
                                    )

                                    refreshed_disclosure_score = max(
                                        0,
                                        min(
                                            100,
                                            refreshed_disclosure_score
                                        )
                                    )

                            refreshed_total_score = round(
                                refreshed_chart_score * 0.4
                                + refreshed_disclosure_score * 0.6
                            )

                            if refreshed_total_score >= 85:
                                refreshed_grade = "A"
                            elif refreshed_total_score >= 70:
                                refreshed_grade = "B"
                            elif refreshed_total_score >= 55:
                                refreshed_grade = "C"
                            else:
                                refreshed_grade = "D"

                            # ------------------------------------------
                            # 관심종목 점수 변동 기록 저장
                            # ------------------------------------------
                            history_file = "watchlist_history.csv"

                            previous_chart_score = int(
                                float(selected_watchlist_row["차트 점수"])
                            )

                            previous_disclosure_score = int(
                                float(selected_watchlist_row["공시 점수"])
                            )

                            previous_total_score = int(
                                float(selected_watchlist_row["종합 점수"])
                            )

                            previous_grade = str(
                                selected_watchlist_row["종합 등급"]
                            )

                            history_row = pd.DataFrame([{
                                "종목명": selected_watchlist_stock,
                                "종목코드": selected_watchlist_code,
                                "기록일시": datetime.today().strftime(
                                    "%Y-%m-%d %H:%M:%S"
                                ),
                                "이전 차트 점수": previous_chart_score,
                                "현재 차트 점수": refreshed_chart_score,
                                "차트 점수 변화": (
                                    refreshed_chart_score
                                    - previous_chart_score
                                ),
                                "이전 공시 점수": previous_disclosure_score,
                                "현재 공시 점수": refreshed_disclosure_score,
                                "공시 점수 변화": (
                                    refreshed_disclosure_score
                                    - previous_disclosure_score
                                ),
                                "이전 종합 점수": previous_total_score,
                                "현재 종합 점수": refreshed_total_score,
                                "종합 점수 변화": (
                                    refreshed_total_score
                                    - previous_total_score
                                ),
                                "이전 등급": previous_grade,
                                "현재 등급": refreshed_grade
                            }])

                            history_record = (
                                history_row.iloc[0].to_dict()
                            )

                            save_history = should_save_score_history(
                                history_file,
                                history_record
                            )

                            if save_history:
                                if os.path.exists(history_file):
                                    history_df = pd.read_csv(
                                        history_file,
                                        dtype={"종목코드": str}
                                    )

                                    history_df = pd.concat(
                                        [history_df, history_row],
                                        ignore_index=True
                                    )

                                else:
                                    history_df = history_row

                                history_df.to_csv(
                                    history_file,
                                    index=False,
                                    encoding="utf-8-sig"
                                )

                                st.session_state[
                                    "individual_history_saved"
                                ] = True

                            else:
                                st.session_state[
                                    "individual_history_saved"
                                ] = False

                            target_index = watchlist_df[
                                watchlist_df["종목명"]
                                == selected_watchlist_stock
                            ].index[0]

                            watchlist_df.loc[
                                target_index,
                                "차트 점수"
                            ] = refreshed_chart_score

                            watchlist_df.loc[
                                target_index,
                                "공시 점수"
                            ] = refreshed_disclosure_score

                            watchlist_df.loc[
                                target_index,
                                "종합 점수"
                            ] = refreshed_total_score

                            watchlist_df.loc[
                                target_index,
                                "종합 등급"
                            ] = refreshed_grade

                            watchlist_df.loc[
                                target_index,
                                "저장 날짜"
                            ] = datetime.today().strftime("%Y-%m-%d")

                            watchlist_df.to_csv(
                                watchlist_file,
                                index=False,
                                encoding="utf-8-sig"
                            )

                            if st.session_state.get(
                                "individual_history_saved",
                                False
                            ):
                                st.session_state[
                                    "individual_refresh_message"
                                ] = (
                                    f"{selected_watchlist_stock}의 "
                                    "점수를 갱신하고 변동 기록을 "
                                    "저장했습니다."
                                )

                            else:
                                st.session_state[
                                    "individual_refresh_info"
                                ] = (
                                    f"{selected_watchlist_stock}의 "
                                    "점수는 갱신했지만, 오늘 저장된 "
                                    "최근 기록과 점수가 같아 변동 기록은 "
                                    "추가하지 않았습니다."
                                )

                            st.rerun()

                    except Exception as error:
                        st.error(
                            f"관심종목 점수 갱신 오류: {error}"
                        )

                if st.button(
                    "선택 관심종목 상세 차트 보기",
                    key="watchlist_detail_chart"
                ):
                    try:
                        selected_watchlist_row = watchlist_df[
                            watchlist_df["종목명"]
                            == selected_watchlist_stock
                        ].iloc[0]

                        selected_watchlist_code = str(
                            selected_watchlist_row["종목코드"]
                        ).zfill(6)

                        chart_start_date = (
                            datetime.today() - timedelta(days=180)
                        )

                        watchlist_chart_data = fdr.DataReader(
                            selected_watchlist_code,
                            chart_start_date.strftime("%Y-%m-%d")
                        )

                        if watchlist_chart_data.empty:
                            st.warning("주가 데이터를 찾지 못했습니다.")

                        else:
                            watchlist_chart_data["5일선"] = (
                                watchlist_chart_data["Close"]
                                .rolling(5)
                                .mean()
                            )

                            watchlist_chart_data["20일선"] = (
                                watchlist_chart_data["Close"]
                                .rolling(20)
                                .mean()
                            )

                            watchlist_chart = go.Figure()

                            watchlist_chart.add_trace(
                                go.Candlestick(
                                    x=watchlist_chart_data.index,
                                    open=watchlist_chart_data["Open"],
                                    high=watchlist_chart_data["High"],
                                    low=watchlist_chart_data["Low"],
                                    close=watchlist_chart_data["Close"],
                                    name="주가"
                                )
                            )

                            watchlist_chart.add_trace(
                                go.Scatter(
                                    x=watchlist_chart_data.index,
                                    y=watchlist_chart_data["5일선"],
                                    name="5일선"
                                )
                            )

                            watchlist_chart.add_trace(
                                go.Scatter(
                                    x=watchlist_chart_data.index,
                                    y=watchlist_chart_data["20일선"],
                                    name="20일선"
                                )
                            )

                            watchlist_chart.update_layout(
                                title=(
                                    f"{selected_watchlist_stock} "
                                    "관심종목 상세 차트"
                                ),
                                xaxis_rangeslider_visible=False,
                                height=600
                            )

                            st.plotly_chart(
                                watchlist_chart,
                                width="stretch"
                            )

                            st.divider()
                            st.subheader(
                                f"📢 {selected_watchlist_stock} 최근 30일 공시"
                            )

                            corp_codes = load_dart_corp_codes()

                            matched_corp = corp_codes[
                                corp_codes["stock_code"]
                                == selected_watchlist_code
                            ]

                            if matched_corp.empty:
                                st.info(
                                    "해당 종목의 DART 기업코드를 "
                                    "찾지 못했습니다."
                                )

                            else:
                                selected_corp_code = (
                                    matched_corp.iloc[0]["corp_code"]
                                )

                                disclosure_end_date = datetime.today()
                                disclosure_start_date = (
                                    disclosure_end_date
                                    - timedelta(days=30)
                                )

                                disclosure_url = (
                                    "https://opendart.fss.or.kr/"
                                    "api/list.json"
                                )

                                disclosure_params = {
                                    "crtfc_key": dart_api_key,
                                    "corp_code": selected_corp_code,
                                    "bgn_de": disclosure_start_date.strftime(
                                        "%Y%m%d"
                                    ),
                                    "end_de": disclosure_end_date.strftime(
                                        "%Y%m%d"
                                    ),
                                    "page_count": 100
                                }

                                disclosure_response = requests.get(
                                    disclosure_url,
                                    params=disclosure_params,
                                    timeout=10
                                )

                                disclosure_result = (
                                    disclosure_response.json()
                                )

                                if (
                                    disclosure_result.get("status")
                                    == "013"
                                ):
                                    st.info(
                                        "최근 30일 동안 등록된 공시가 "
                                        "없습니다."
                                    )

                                elif (
                                    disclosure_result.get("status")
                                    != "000"
                                ):
                                    st.warning(
                                        "공시를 불러오지 못했습니다: "
                                        + disclosure_result.get(
                                            "message",
                                            "알 수 없는 오류"
                                        )
                                    )

                                else:
                                    disclosure_rows = []

                                    for disclosure_item in (
                                        disclosure_result["list"]
                                    ):
                                        report_name = disclosure_item[
                                            "report_nm"
                                        ]

                                        category, score, reason = (
                                            analyze_disclosure(
                                                report_name
                                            )
                                        )

                                        receipt_number = disclosure_item[
                                            "rcept_no"
                                        ]

                                        disclosure_rows.append({
                                            "공시일": disclosure_item[
                                                "rcept_dt"
                                            ],
                                            "공시 제목": report_name,
                                            "분류": category,
                                            "점수": score,
                                            "판단 근거": reason,
                                            "제출인": disclosure_item[
                                                "flr_nm"
                                            ],
                                            "공시 보기": (
                                                "https://dart.fss.or.kr/"
                                                "dsaf001/main.do?"
                                                f"rcpNo={receipt_number}"
                                            )
                                        })

                                    disclosure_df = pd.DataFrame(
                                        disclosure_rows
                                    )

                                    disclosure_df["공시일"] = pd.to_datetime(
                                        disclosure_df["공시일"],
                                        format="%Y%m%d"
                                    ).dt.strftime("%Y-%m-%d")

                                    disclosure_df = (
                                        disclosure_df.sort_values(
                                            "공시일",
                                            ascending=False
                                        )
                                    )

                                    st.success(
                                        f"최근 공시 "
                                        f"{len(disclosure_df)}건을 "
                                        "불러왔습니다."
                                    )

                                    st.dataframe(
                                        disclosure_df,
                                        width="stretch",
                                        hide_index=True,
                                        column_config={
                                            "공시 보기":
                                                st.column_config.LinkColumn(
                                                    "공시 원문",
                                                    display_text="열기"
                                                )
                                        }
                                    ) 

                    except Exception as error:
                        st.error(
                            f"관심종목 차트를 불러오지 못했습니다: {error}"
                        )
            with st.expander(
                "🗑️ 관심종목 삭제",
                expanded=False
            ):
                delete_watchlist_confirmed = st.checkbox(
                    f"{selected_watchlist_stock} 종목 삭제에 동의합니다.",
                    key="confirm_delete_watchlist_stock"
                )
                if st.button(
                    "선택 종목 삭제",
                    key="delete_watchlist_stock",
                    disabled=not delete_watchlist_confirmed
                ):
                    if not delete_watchlist_confirmed:
                        st.warning(
                            "삭제 동의 체크박스를 먼저 선택해주세요."
                        )
                        st.stop()

                    watchlist_df = watchlist_df[
                        watchlist_df["종목명"]
                        != selected_watchlist_stock
                    ]

                    watchlist_df.to_csv(
                        watchlist_file,
                        index=False,
                        encoding="utf-8-sig"
                    )

                    st.success(
                        f"{selected_watchlist_stock}을 "
                        "관심종목에서 삭제했습니다."
                    )

                    st.rerun()

    else:
        st.info(
            "아직 저장된 관심종목이 없습니다. "
            "추천 후보 탭에서 관심종목을 추가하세요."
        )
