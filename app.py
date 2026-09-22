import streamlit as st
import pandas as pd
import requests

# 페이지 기본 설정
st.set_page_config(page_title="모두의 점심", page_icon="🍽️")

# 메뉴 목록
MENU_LIST = ["제육볶음", "스시", "수제버거", "파스타", "타코", "샐러드"]

# 요청 시간 제한 (초)
REQUEST_TIMEOUT = 5

# 시트 열 순서: 시각, 팀원, 메뉴, 구분
COLUMN_NAMES = ["시각", "팀원", "메뉴", "구분"]


def get_sheet_url():
    """secrets에서 시트 연결 주소를 읽어온다. 화면에는 절대 노출하지 않는다."""
    return st.secrets["SHEET_URL"]


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

        # data가 머리글을 포함한 2차원 리스트라고 가정 (예: [[시각, 팀원, 메뉴, 구분], [...], ...])
        if isinstance(data, list) and len(data) > 0:
            header = data[0]
            rows = data[1:]
            df = pd.DataFrame(rows, columns=header)
        else:
            df = pd.DataFrame(columns=COLUMN_NAMES)

        return True, df

    except Exception:
        # 실패 원인(주소, 상세 오류)을 화면에 노출하지 않는다.
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


# ----------------------------
# 화면 구성 시작
# ----------------------------

st.title("🍽️ 모두의 점심")
st.write("오늘 점심 메뉴, 함께 골라봐요! 닉네임과 먹고 싶은 메뉴를 선택하고 투표해주세요.")

st.divider()

# 입력 폼 (기존과 동일하게 유지)
with st.form(key="vote_form", clear_on_submit=True):
    nickname = st.text_input("닉네임을 입력하세요")
    menu = st.selectbox("먹고 싶은 메뉴를 선택하세요", MENU_LIST)
    submitted = st.form_submit_button("투표하기")

    if submitted:
        if nickname.strip() == "":
            st.warning("닉네임을 입력해주세요!")
        else:
            with st.spinner("투표를 저장하는 중..."):
                ok, _ = submit_vote(nickname.strip(), menu)

            if ok:
                st.success(f"{nickname}님, '{menu}'에 투표 완료! 🎉")
                # 저장 성공 후 최신 기록 다시 읽기
                with st.spinner("최신 결과를 불러오는 중..."):
                    read_ok, df = fetch_records()

                if read_ok:
                    st.session_state["last_df"] = df
                    st.session_state["read_failed"] = False
                else:
                    st.session_state["read_failed"] = True
            else:
                st.error("투표 저장에 실패했어요. 잠시 후 다시 시도해주세요.")

st.divider()

# 결과 새로 읽기 버튼
col1, col2 = st.columns([1, 3])
with col1:
    refresh_clicked = st.button("🔄 결과 새로 읽기")

if refresh_clicked:
    with st.spinner("결과를 불러오는 중..."):
        read_ok, df = fetch_records()

    if read_ok:
        st.session_state["last_df"] = df
        st.session_state["read_failed"] = False
    else:
        st.session_state["read_failed"] = True

# ----------------------------
# 결과 표시
# ----------------------------

st.subheader("📋 투표 현황")

# 읽기 실패 상태라면, 주소나 상세 오류 없이 안내만 표시
if st.session_state.get("read_failed"):
    st.error("현재 결과를 불러올 수 없어요. 네트워크 상태를 확인하고 잠시 후 다시 시도해주세요.")

elif "last_df" in st.session_state:
    df = st.session_state["last_df"]

    if df is None or len(df) == 0:
        st.info("아직 투표가 없어요. 첫 번째로 투표해보세요!")
    else:
        st.dataframe(df, use_container_width=True)

        if "메뉴" in df.columns:
            st.subheader("📊 메뉴별 득표수")
            menu_counts = df["메뉴"].value_counts()
            st.bar_chart(menu_counts)

        st.write(f"총 투표 수: **{len(df)}표**")

else:
    st.info("아직 결과를 불러오지 않았어요. '결과 새로 읽기' 버튼을 눌러보세요.")
