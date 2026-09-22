import streamlit as st
import pandas as pd

# 페이지 기본 설정
st.set_page_config(page_title="모두의 점심", page_icon="🍽️")

# 메뉴 목록
MENU_LIST = ["제육볶음", "스시", "수제버거", "파스타", "타코", "샐러드"]

# session_state 초기화 (투표 기록을 저장할 리스트)
if "votes" not in st.session_state:
    st.session_state.votes = []

st.title("🍽️ 모두의 점심")
st.write("오늘 점심 메뉴, 함께 골라봐요! 닉네임과 먹고 싶은 메뉴를 선택하고 투표해주세요.")

st.divider()

# 입력 폼
with st.form(key="vote_form", clear_on_submit=True):
    nickname = st.text_input("닉네임을 입력하세요")
    menu = st.selectbox("먹고 싶은 메뉴를 선택하세요", MENU_LIST)
    submitted = st.form_submit_button("투표하기")

    if submitted:
        if nickname.strip() == "":
            st.warning("닉네임을 입력해주세요!")
        else:
            # session_state 리스트에 투표 정보 추가
            st.session_state.votes.append({
                "닉네임": nickname.strip(),
                "메뉴": menu
            })
            st.success(f"{nickname}님, '{menu}'에 투표 완료! 🎉")

st.divider()

# 투표 결과 표시
st.subheader("📋 투표 현황")

if len(st.session_state.votes) == 0:
    st.info("아직 투표가 없어요. 첫 번째로 투표해보세요!")
else:
    # 전체 투표 목록 표
    df = pd.DataFrame(st.session_state.votes)
    st.dataframe(df, use_container_width=True)

    st.subheader("📊 메뉴별 득표수")
    menu_counts = df["메뉴"].value_counts()
    st.bar_chart(menu_counts)

    # 총 투표 수
    st.write(f"총 투표 수: **{len(st.session_state.votes)}표**")
