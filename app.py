import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from streamlit_autorefresh import st_autorefresh

# 페이지 기본 설정
st.set_page_config(page_title="모두의 점심", page_icon="🍽️")

# 메뉴 목록
MENU_LIST = ["제육볶음", "스시", "수제버거", "파스타", "타코", "샐러드"]

# 요청 시간 제한 (초)
REQUEST_TIMEOUT = 5

# 시트 열 순서: 시각, 팀원, 메뉴, 구분
COLUMN_NAMES = ["시각", "팀원", "메뉴", "구분"]

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


def get_sheet_url():
    """secrets에서 시트 연결 주소를 읽어온다. 화면에는 절대 노출하지 않는다."""
    return st.secrets["SHEET_URL"]


def now_kst_str():
    """현재 한국 시간을 문자열로 반환 (화면 표시용)"""
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def today_kst_str():
    """오늘 날짜(한국 기준)를 'YYYY-MM-DD' 형태로 반환"""
    return datetime.now(KST).strftime("%Y-%m-%d")


def fetch_records():
    """
    구글 시트(연결 프로그램)에서 기록을 읽어온다.
    성공하면 (True, DataFrame) 반환.
    실패하면 (False, None) 반환. -> 빈 목록으로 대체하지 않음!
    """
    try:
        url = get_sheet_url()
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list) and len(data) > 0:
            header = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=header)
        else:
            df = pd.DataFrame(columns=COLUMN_NAMES)

        return True, df

    except Exception:
        return False, None


def submit_vote(nickname, menu):
    """
    구글 시트(연결 프로그램)에 투표를 저장한다.
    성공하면 (True, 응답데이터) 반환.
    실패하거나 ok가 true가 아니면 (False, None) 반환.
    """
    try:
        url = get_sheet_url()
        payload = {
            "member": nickname,
            "menu": menu,
            "type": "먹고싶다",
        }
        response = requests.post(url, data=payload, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = response.json()

        if result.get("ok") is True:
            return True, result
        else:
            return False, None

    except Exception:
        return False, None


def compute_today_last_votes(df):
    """
    df(전체 기록)에서
    1) 오늘(한국 기준) 날짜의 '먹고싶다' 기록만 추출
    2) 같은 닉네임끼리는 시트에서 가장 뒤(마지막)에 있는 행만 남김
    결과: 닉네임별 최종 투표 DataFrame 반환
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=COLUMN_NAMES)

    work = df.copy()

    # 필요한 열이 없으면 빈 결과 반환 (형식이 예상과 다른 경우 방어)
    for col in COLUMN_NAMES:
        if col not in work.columns:
            return pd.DataFrame(columns=COLUMN_NAMES)

    # 원래 행 순서를 기억해두기 (시트에서 뒤에 있는 행 = 나중 순번)
    work = work.reset_index(drop=True)
    work["__원래순번"] = work.index

    # 구분이 '먹고싶다'인 것만
    work = work[work["구분"] == "먹고싶다"]

    # 시각 문자열에서 날짜 부분만 뽑아 오늘(한국 기준)과 비교
    # 시각 형식이 "YYYY-MM-DD HH:MM:SS" 등으로 시작한다고 가정
    today = today_kst_str()
    work["__날짜"] = work["시각"].astype(str).str.slice(0, 10)
    work = work[work["__날짜"] == today]

    if len(work) == 0:
        return pd.DataFrame(columns=COLUMN_NAMES)

    # 같은 닉네임(팀원) 중 __원래순번이 가장 큰(=시트에서 가장 뒤) 행만 남기기
    work = work.sort_values("__원래순번")
    last_rows = work.groupby("팀원", as_index=False).tail(1)

    return last_rows.drop(columns=["__원래순번", "__날짜"])


def compute_menu_counts(last_votes_df):
    """
    메뉴 목록 전체를 기준으로 득표수를 센다 (0표 메뉴도 포함).
    반환: 메뉴 이름을 인덱스로 하는 Series
    """
    counts = pd.Series(0, index=MENU_LIST, dtype=int)

    if last_votes_df is not None and len(last_votes_df) > 0:
        vote_counts = last_votes_df["메뉴"].value_counts()
        for menu_name, cnt in vote_counts.items():
            if menu_name in counts.index:
                counts[menu_name] = cnt

    return counts


def get_top_menus(menu_counts):
    """공동 1위 메뉴 목록과 최고 득표수를 반환"""
    max_count = menu_counts.max()
    if max_count == 0:
        return [], 0
    top_menus = menu_counts[menu_counts == max_count].index.tolist()
    return top_menus, max_count


def render_result_area():
    """결과 영역을 그리는 함수 (자동 새로고침 대상)"""

    st.subheader("📋 오늘의 투표 결과")

    if st.session_state.get("read_failed"):
        st.error("현재 결과를 불러올 수 없어요. 네트워크 상태를 확인하고 잠시 후 다시 시도해주세요.")
        return

    if "last_df" not in st.session_state:
        st.info("아직 결과를 불러오지 않았어요. '결과 새로 읽기' 버튼을 눌러보세요.")
        return

    raw_df = st.session_state["last_df"]
    last_votes_df = compute_today_last_votes(raw_df)

    voter_count = len(last_votes_df)

    if voter_count == 0:
        st.info("아직 투표가 없습니다.")
    else:
        st.write(f"오늘 투표한 사람 수: **{voter_count}명**")

        menu_counts = compute_menu_counts(last_votes_df)

        st.subheader("📊 메뉴별 득표 수")
        st.bar_chart(menu_counts)

        # 표 형태로도 보여주기
        count_table = menu_counts.reset_index()
        count_table.columns = ["메뉴", "득표수"]
        st.dataframe(count_table, use_container_width=True, hide_index=True)

        top_menus, max_count = get_top_menus(menu_counts)
        if top_menus:
            menus_str = ", ".join(top_menus)
            st.success(f"🏆 오늘의 1위 메뉴: **{menus_str}** ({max_count}표)")

    # 마지막으로 읽은 시각 표시
    if "last_read_time" in st.session_state:
        st.caption(f"마지막으로 읽은 시각: {st.session_state['last_read_time']}")


def refresh_records():
    """시트에서 기록을 다시 읽어와 session_state에 반영"""
    read_ok, df = fetch_records()
    if read_ok:
        st.session_state["last_df"] = df
        st.session_state["read_failed"] = False
        st.session_state["last_read_time"] = now_kst_str()
    else:
        st.session_state["read_failed"] = True


# ----------------------------
# 화면 구성 시작
# ----------------------------

st.title("🍽️ 모두의 점심")
st.write("오늘 점심 메뉴, 함께 골라봐요! 닉네임과 먹고 싶은 메뉴를 선택하고 투표해주세요.")

st.divider()

# 입력 중인 닉네임/메뉴를 유지하기 위한 session_state 초기화
if "input_nickname" not in st.session_state:
    st.session_state["input_nickname"] = ""
if "input_menu" not in st.session_state:
    st.session_state["input_menu"] = MENU_LIST[0]

# 입력 폼 (자동 새로고침 되어도 값 유지되도록 key 사용, clear_on_submit=False)
with st.form(key="vote_form", clear_on_submit=False):
    nickname = st.text_input("닉네임을 입력하세요", key="input_nickname")
    menu = st.selectbox(
        "먹고 싶은 메뉴를 선택하세요",
        MENU_LIST,
        key="input_menu",
    )
    submitted = st.form_submit_button("투표하기")

    if submitted:
        if nickname.strip() == "":
            st.warning("닉네임을 입력해주세요!")
        else:
            with st.spinner("투표를 저장하는 중..."):
                ok, _ = submit_vote(nickname.strip(), menu)

            if ok:
                st.success(f"{nickname}님, '{menu}'에 투표 완료! 🎉")
                # 저장 성공 후 최신 기록 바로 다시 읽기
                with st.spinner("최신 결과를 불러오는 중..."):
                    refresh_records()
            else:
                st.error("투표 저장에 실패했어요. 잠시 후 다시 시도해주세요.")

st.divider()

# 결과 새로 읽기 버튼
col1, col2 = st.columns([1, 3])
with col1:
    refresh_clicked = st.button("🔄 결과 새로 읽기")

if refresh_clicked:
    with st.spinner("결과를 불러오는 중..."):
        refresh_records()

# 결과 영역만 10초마다 자동 새로고침 (key를 고정해 카운터 유지)
st_autorefresh(interval=10_000, key="result_autorefresh")

# 자동 새로고침으로 인한 재실행일 때도 최신 데이터를 읽어오기
# (버튼을 누르지 않아도 10초마다 최신 결과 반영)
if "last_df" not in st.session_state or refresh_clicked is False:
    # 처음 실행되었거나, 자동 새로고침으로 재실행된 경우에도 최신화
    with st.spinner("결과를 불러오는 중..."):
        refresh_records()

render_result_area()
