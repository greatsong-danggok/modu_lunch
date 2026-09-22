# app.py
import os
from datetime import datetime, timedelta

import streamlit as st
from supabase import create_client, Client

# ------------------------------------------------------------------
# Supabase 클라이언트 초기화
# ------------------------------------------------------------------
def get_supabase_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_PUBLISHABLE_KEY"]
    return create_client(url, key)


# ------------------------------------------------------------------
# 한국 시간 기준 날짜 헬퍼
# ------------------------------------------------------------------
def korea_now() -> datetime:
    return datetime.now().astimezone(
        timedelta(hours=9)
    )


def korea_today_str() -> str:
    return korea_now().strftime("%Y-%m-%d")


def korea_days_ago_str(days: int) -> str:
    return (korea_now() - timedelta(days=days)).strftime("%Y-%m-%d")


# ------------------------------------------------------------------
# 투표 저장
# ------------------------------------------------------------------
def save_vote(supabase: Client, name: str, menu: str) -> None:
    response = (
        supabase.table("votes")
        .insert({"name": name, "menu": menu, "kind": "희망메뉴"})
        .execute()
    )
    if response.error:
        raise response.error
    return response.data


# ------------------------------------------------------------------
# 식사 기록 저장 (중복 거절만 따로 처리)
# ------------------------------------------------------------------
def save_meal(supabase: Client, name: str, menu: str) -> None:
    response = (
        supabase.table("votes")
        .insert({"name": name, "menu": menu, "kind": "식사완료"})
        .execute()
    )
    if response.error:
        msg = str(response.error).lower()
        # 중복 제약으로 인한 거절로 볼 수 있는 경우만 별도 안내
        if "duplicate" in msg or "unique" in msg or "constraint" in msg:
            raise ValueError("이미 기록한 식사입니다")
        raise response.error
    return response.data


# ------------------------------------------------------------------
# 오늘 마지막 투표 조회
# ------------------------------------------------------------------
def get_last_vote_for_today(supabase: Client, name: str) -> dict | None:
    today = korea_today_str()
    response = (
        supabase.table("votes")
        .select("*")
        .eq("name", name)
        .eq("kind", "희망메뉴")
        .gte("created_at", today + "T00:00:00")
        .order("created_at", desc=True)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if response.error:
        raise response.error
    rows = response.data or []
    return rows[0] if rows else None


# ------------------------------------------------------------------
# 오늘의 투표 집계 (희망메뉴만 사용)
# ------------------------------------------------------------------
def get_today_vote_counts(supabase: Client) -> dict[str, int]:
    today = korea_today_str()
    response = (
        supabase.table("votes")
        .select("menu")
        .eq("kind", "희망메뉴")
        .gte("created_at", today + "T00:00:00")
        .execute()
    )
    if response.error:
        raise response.error

    counts: dict[str, int] = {}
    for row in response.data or []:
        menu = row.get("menu")
        if menu:
            counts[menu] = counts.get(menu, 0) + 1
    return counts


# ------------------------------------------------------------------
# 최근 7일 식사 기록 조회 (식사완료만 사용)
# 식사 기록은 보통 건수가 많지 않아 한 번 조회로 충분한 경우가 많지만,
# 요청이 크면 이어서 읽는 방식도 대비해 둔다.
# ------------------------------------------------------------------
def get_recent_meals(supabase: Client, days: int = 7) -> list[dict]:
    start = korea_days_ago_str(days)
    rows: list[dict] = []
    cursor = None

    while True:
        query = (
            supabase.table("votes")
            .select("*")
            .eq("kind", "식사완료")
            .gte("created_at", start + "T00:00:00")
            .order("created_at", desc=True)
        )
        if cursor:
            query = query.cursor(cursor)

        response = query.limit(200).execute()

        if response.error:
            raise response.error

        page = response.data or []
        rows.extend(page)

        # 응답이 커서 이어 읽어야 하는 경우 대비
        if not response.has_more:
            break
        cursor = response.cursor

        # 실습용 안전장치: 무한 반복 방지
        if len(rows) > 2000:
            break

    return rows


# ------------------------------------------------------------------
# Streamlit 화면
# ------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="모두의 점심", layout="centered")

    supabase = get_supabase_client()

    # 예시 메뉴 목록 (실제 앱 구성에 맞게 조정)
    menus = ["김치찌개", "된장찌개", "제육볶음", "불고기", "비빔밥", "라면"]

    st.title("모두의 점심")

    # ------------------------------------------------------------------
    # 입력 영역
    # ------------------------------------------------------------------
    col1, col2 = st.columns(2)
    with col1:
        name = st.text_input("닉네임", value=st.session_state.get("name", ""))
        if name:
            st.session_state["name"] = name
    with col2:
        menu = st.selectbox("메뉴", options=menus)

    vote_btn = st.button("먹고 싶다 투표")
    meal_btn = st.button("실제 식사 기록")

    # ------------------------------------------------------------------
    # 투표 처리
    # ------------------------------------------------------------------
    if vote_btn:
        if not name.strip():
            st.warning("닉네임을 입력해 주세요.")
        else:
            try:
                save_vote(supabase, name.strip(), menu)
                st.success("투표가 저장되었습니다.")
            except Exception as e:
                st.error(f"투표 저장 중 오류가 발생했습니다: {e}")

    # ------------------------------------------------------------------
    # 식사 기록 처리
    # ------------------------------------------------------------------
    if meal_btn:
        if not name.strip():
            st.warning("닉네임을 입력해 주세요.")
        else:
            try:
                save_meal(supabase, name.strip(), menu)
                st.success("식사 기록이 저장되었습니다.")
                # 성공 응답을 확인한 뒤 결과만 다시 읽기
                st.rerun()
            except ValueError as e:
                st.warning(str(e))
            except Exception as e:
                st.error(f"식사 기록 중 오류가 발생했습니다: {e}")

    # ------------------------------------------------------------------
    # 결과 영역 (10초마다 자동 새로 읽기)
    # ------------------------------------------------------------------
    last_refresh_key = "last_refresh_time"
    now = datetime.now()

    if last_refresh_key not in st.session_state:
        st.session_state[last_refresh_key] = now

    auto_refresh = False
    if (now - st.session_state[last_refresh_key]).total_seconds() >= 10:
        auto_refresh = True
        st.session_state[last_refresh_key] = now

    manually_refreshed = st.button("결과 새로 읽기")
    if manually_refreshed:
        st.session_state[last_refresh_key] = now
        auto_refresh = True

    if auto_refresh or manually_refreshed:
        try:
            vote_counts = get_today_vote_counts(supabase)
            meals = get_recent_meals(supabase, days=7)
        except Exception as e:
            st.error(f"결과를 읽는 중 오류가 발생했습니다: {e}")
            vote_counts, meals = {}, []
    else:
        # 이전 세션에서 읽은 값이 있으면 유지
        vote_counts = st.session_state.get("vote_counts", {})
        meals = st.session_state.get("meals", [])

    # 조회 시각 표시
    if vote_counts or meals:
        st.caption(f"마지막 조회 시각: {korea_now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ------------------------------------------------------------------
    # 오늘 투표 집계 표시
    # ------------------------------------------------------------------
    st.subheader("오늘의 투표")
    if not vote_counts:
        st.info("아직 오늘 투표가 없습니다.")
    else:
        sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
        max_count = sorted_votes[0][1] if sorted_votes else 0
        winners = [m for m, c in sorted_votes if c == max_count]

        st.write("### 1위 메뉴")
        if len(winners) == 1:
            st.success(f"{winners[0]} — {max_count}표")
        else:
            st.success(f"공동 1위: {', '.join(winners)} — 각 {max_count}표")

        st.write("### 메뉴별 득표")
        for menu_name, count in sorted_votes:
            st.write(f"- {menu_name}: {count}표")

    # ------------------------------------------------------------------
    # 최근 식사 기록 표시
    # ------------------------------------------------------------------
    st.subheader("최근 7일 식사 기록")
    if not meals:
        st.info("최근 식사 기록이 없습니다.")
    else:
        for row in meals:
            created = row.get("created_at", "")
            st.write(f"- {row.get('name', '전체')} / {row.get('menu', '')} / {created}")

    # 세션에 저장해 두면 자동 새로 읽기 구간에서도 값이 유지됩니다.
    st.session_state["vote_counts"] = vote_counts
    st.session_state["meals"] = meals


if __name__ == "__main__":
    main()
