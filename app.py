import streamlit as st
import pandas as pd

from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from streamlit_autorefresh import st_autorefresh


# ----------------------------
# 기본 설정
# ----------------------------

st.set_page_config(
    page_title="모두의 점심",
    page_icon="🍽️",
)

MENU_LIST = [
    "제육볶음",
    "스시",
    "수제버거",
    "파스타",
    "타코",
    "샐러드",
]

# 한국 시간대 UTC+9
KST = timezone(timedelta(hours=9))

# Supabase는 기본적으로 한 번에 최대 1,000행까지 반환하므로
# 그 이상이면 range()로 이어서 읽는다.
PAGE_SIZE = 1000

DB_COLUMNS = [
    "id",
    "name",
    "menu",
    "kind",
    "created_at",
]


# ----------------------------
# Supabase 연결
# ----------------------------

@st.cache_resource
def get_supabase() -> Client:
    """
    Streamlit Secrets에서 Supabase 연결 정보를 읽어
    Supabase 클라이언트를 만든다.
    """
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_PUBLISHABLE_KEY"]

    return create_client(url, key)


# ----------------------------
# 날짜 / 시간
# ----------------------------

def now_kst():
    """현재 한국 시간을 datetime으로 반환"""
    return datetime.now(KST)


def now_kst_str():
    """현재 한국 시간을 화면 표시용 문자열로 반환"""
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")


def to_utc_iso(dt):
    """
    시간대가 포함된 datetime을
    Supabase 조회에 사용할 UTC ISO 문자열로 변환
    """
    return (
        dt.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def get_date_ranges():
    """
    한국 시간을 기준으로 필요한 조회 범위를 만든다.

    today_start:
        오늘 00:00

    tomorrow_start:
        내일 00:00

    seven_days_ago_start:
        오늘을 제외한 최근 7일의 시작 시각
    """
    now = now_kst()

    today_start = now.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    tomorrow_start = today_start + timedelta(days=1)
    seven_days_ago_start = today_start - timedelta(days=7)

    return {
        "today_start": today_start,
        "tomorrow_start": tomorrow_start,
        "seven_days_ago_start": seven_days_ago_start,
    }


# ----------------------------
# Supabase 조회
# ----------------------------

def fetch_rows(kind, start_dt, end_dt):
    """
    지정한 기간과 kind에 해당하는 기록만 Supabase에서 읽는다.

    결과가 PAGE_SIZE를 넘으면 range()를 사용해
    빠진 기록 없이 이어서 읽는다.
    """
    supabase = get_supabase()

    start_iso = to_utc_iso(start_dt)
    end_iso = to_utc_iso(end_dt)

    rows = []
    offset = 0

    while True:
        response = (
            supabase
            .table("votes")
            .select("id,name,menu,kind,created_at")
            .eq("kind", kind)
            .gte("created_at", start_iso)
            .lt("created_at", end_iso)
            .order("created_at", desc=False)
            .order("id", desc=False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )

        batch = response.data or []
        rows.extend(batch)

        if len(batch) < PAGE_SIZE:
            break

        offset += PAGE_SIZE

    return rows


def fetch_records():
    """
    화면에 필요한 기록만 읽는다.

    1. 오늘의 희망메뉴 투표
    2. 오늘을 제외한 최근 7일의 식사완료 기록

    성공:
        (True, 오늘 투표 df, 지난 식사 df)

    실패:
        (False, None, None)

    읽기 실패를 빈 목록으로 바꾸지 않는다.
    """
    try:
        ranges = get_date_ranges()

        today_vote_rows = fetch_rows(
            kind="희망메뉴",
            start_dt=ranges["today_start"],
            end_dt=ranges["tomorrow_start"],
        )

        past_meal_rows = fetch_rows(
            kind="식사완료",
            start_dt=ranges["seven_days_ago_start"],
            end_dt=ranges["today_start"],
        )

        today_votes_df = pd.DataFrame(
            today_vote_rows,
            columns=DB_COLUMNS,
        )

        past_meals_df = pd.DataFrame(
            past_meal_rows,
            columns=DB_COLUMNS,
        )

        return True, today_votes_df, past_meals_df

    except Exception:
        return False, None, None


def refresh_records():
    """
    Supabase에서 최신 기록을 읽어서 session_state에 저장한다.

    실패하면 기존 기록을 빈 데이터로 덮어쓰지 않는다.
    """
    read_ok, today_votes_df, past_meals_df = fetch_records()

    if read_ok:
        st.session_state["today_votes_df"] = today_votes_df
        st.session_state["past_meals_df"] = past_meals_df
        st.session_state["read_failed"] = False
        st.session_state["last_read_time"] = now_kst_str()

    else:
        st.session_state["read_failed"] = True


# ----------------------------
# Supabase 저장
# ----------------------------

def submit_vote(nickname, menu):
    """
    희망 메뉴 투표를 저장한다.

    id와 created_at은 보내지 않고
    데이터베이스가 자동으로 만든다.
    """
    try:
        supabase = get_supabase()

        payload = {
            "name": nickname,
            "menu": menu,
            "kind": "희망메뉴",
        }

        response = (
            supabase
            .table("votes")
            .insert(payload)
            .select("id,created_at")
            .execute()
        )

        if response.data:
            return True, response.data

        return False, None

    except Exception:
        return False, None


def get_error_code(error):
    """
    Supabase/PostgREST 오류에서 PostgreSQL 오류 코드를 찾는다.
    """
    code = getattr(error, "code", None)

    if code is not None:
        return str(code)

    # 일부 버전에서는 args 안에 오류 정보가 들어올 수 있으므로 보조 확인
    if getattr(error, "args", None):
        first_arg = error.args[0]

        if isinstance(first_arg, dict):
            code = first_arg.get("code")

            if code is not None:
                return str(code)

    return ""


def submit_meal(menu):
    """
    실제로 먹은 메뉴를 저장한다.

    name = '전체'
    kind = '식사완료'

    같은 한국 날짜 + 같은 메뉴는
    DB의 unique index가 거절한다.

    반환:
        "ok"
        "duplicate"
        "error"
    """
    try:
        supabase = get_supabase()

        payload = {
            "name": "전체",
            "menu": menu,
            "kind": "식사완료",
        }

        response = (
            supabase
            .table("votes")
            .insert(payload)
            .select("id,created_at")
            .execute()
        )

        if response.data:
            return "ok"

        return "error"

    except Exception as error:
        # PostgreSQL unique violation
        if get_error_code(error) == "23505":
            return "duplicate"

        return "error"


# ----------------------------
# 오늘의 투표 계산
# ----------------------------

def compute_today_last_votes(df):
    """
    오늘의 희망메뉴 기록 중
    같은 닉네임의 마지막 투표만 남긴다.

    우선순위:
    1. created_at이 늦은 기록
    2. created_at이 같으면 id가 큰 기록
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=DB_COLUMNS)

    work = df.copy()

    for col in DB_COLUMNS:
        if col not in work.columns:
            return pd.DataFrame(columns=DB_COLUMNS)

    work["created_at"] = pd.to_datetime(
        work["created_at"],
        utc=True,
        errors="coerce",
    )

    work = work.dropna(subset=["created_at"])

    work["id"] = pd.to_numeric(
        work["id"],
        errors="coerce",
    )

    work = work.dropna(subset=["id"])

    work = work.sort_values(
        ["created_at", "id"],
        ascending=[True, True],
    )

    # 같은 닉네임에서는 가장 마지막 기록만 남긴다.
    last_rows = (
        work
        .groupby("name", as_index=False)
        .tail(1)
    )

    return last_rows


def compute_menu_counts(last_votes_df):
    """
    여섯 메뉴 전체의 득표 수를 센다.
    0표 메뉴도 포함한다.
    """
    counts = pd.Series(
        0,
        index=MENU_LIST,
        dtype=int,
    )

    if last_votes_df is None or len(last_votes_df) == 0:
        return counts

    vote_counts = last_votes_df["menu"].value_counts()

    for menu_name, count in vote_counts.items():
        if menu_name in counts.index:
            counts[menu_name] = count

    return counts


def get_top_menus(menu_counts):
    """
    공동 1위 메뉴와 최고 득표수를 반환
    """
    max_count = int(menu_counts.max())

    if max_count == 0:
        return [], 0

    top_menus = (
        menu_counts[menu_counts == max_count]
        .index
        .tolist()
    )

    return top_menus, max_count


# ----------------------------
# 지난 식사 계산
# ----------------------------

def prepare_past_meals(df):
    """
    Supabase의 created_at을 한국 시간으로 바꾸고
    날짜 + 메뉴가 같은 기록은 한 번으로 정리한다.
    """
    if df is None or len(df) == 0:
        return pd.DataFrame(
            columns=["날짜", "메뉴"]
        )

    work = df.copy()

    work["created_at"] = pd.to_datetime(
        work["created_at"],
        utc=True,
        errors="coerce",
    )

    work = work.dropna(subset=["created_at"])

    # UTC 저장 시각 -> 한국 시간
    work["한국시각"] = (
        work["created_at"]
        .dt.tz_convert(KST)
    )

    work["날짜"] = (
        work["한국시각"]
        .dt.strftime("%Y-%m-%d")
    )

    work["id"] = pd.to_numeric(
        work["id"],
        errors="coerce",
    )

    work = work.sort_values(
        ["한국시각", "id"],
        ascending=[True, True],
    )

    # 방어적으로 날짜 + 메뉴 중복 제거
    work = work.drop_duplicates(
        subset=["날짜", "menu"],
        keep="last",
    )

    result = (
        work[["날짜", "menu"]]
        .rename(columns={"menu": "메뉴"})
        .sort_values(
            ["날짜", "메뉴"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )

    return result


def compute_meal_counts(past_meals_df):
    """
    최근 7일 메뉴별 실제 식사 횟수
    """
    counts = pd.Series(
        0,
        index=MENU_LIST,
        dtype=int,
    )

    if past_meals_df is None or len(past_meals_df) == 0:
        return counts

    meal_counts = past_meals_df["메뉴"].value_counts()

    for menu_name, count in meal_counts.items():
        if menu_name in counts.index:
            counts[menu_name] = count

    return counts


# ----------------------------
# 투표 결과 화면
# ----------------------------

def render_vote_result_area():
    st.subheader("📋 오늘의 투표 결과")

    if st.session_state.get("read_failed"):
        st.error(
            "현재 결과를 불러올 수 없어요. "
            "네트워크 상태를 확인하고 잠시 후 다시 시도해주세요."
        )
        return

    if "today_votes_df" not in st.session_state:
        st.info("아직 결과를 불러오지 않았어요.")
        return

    raw_df = st.session_state["today_votes_df"]

    last_votes_df = compute_today_last_votes(raw_df)

    voter_count = len(last_votes_df)

    if voter_count == 0:
        st.info("아직 투표가 없습니다.")
        return

    st.write(
        f"오늘 투표한 사람 수: **{voter_count}명**"
    )

    menu_counts = compute_menu_counts(
        last_votes_df
    )

    st.markdown("#### 📊 메뉴별 득표 수")

    st.bar_chart(menu_counts)

    count_table = (
        menu_counts
        .reset_index()
    )

    count_table.columns = [
        "메뉴",
        "득표수",
    ]

    st.dataframe(
        count_table,
        use_container_width=True,
        hide_index=True,
    )

    top_menus, max_count = get_top_menus(
        menu_counts
    )

    if top_menus:
        menus_str = ", ".join(top_menus)

        st.success(
            f"🏆 오늘의 1위 메뉴: "
            f"**{menus_str}** ({max_count}표)"
        )


# ----------------------------
# 실제 식사 화면
# ----------------------------

def render_meal_area():
    st.subheader("🍱 실제 식사 기록")

    with st.form(
        key="meal_form",
        clear_on_submit=False,
    ):
        meal_menu = st.selectbox(
            "오늘 실제로 먹은 메뉴",
            MENU_LIST,
            key="meal_menu",
        )

        meal_submitted = st.form_submit_button(
            "먹은 메뉴 기록하기"
        )

        if meal_submitted:
            with st.spinner("식사 기록을 저장하는 중..."):
                result = submit_meal(meal_menu)

            if result == "ok":
                st.success(
                    f"'{meal_menu}' 식사 기록을 저장했습니다. 🍽️"
                )

                # 저장 뒤 최신 기록 다시 읽기
                refresh_records()

            elif result == "duplicate":
                st.info(
                    "이미 기록한 식사입니다."
                )

            else:
                st.error(
                    "식사 기록 저장에 실패했어요. "
                    "잠시 후 다시 시도해주세요."
                )

    st.markdown("#### 📅 지난 7일의 식사")

    if st.session_state.get("read_failed"):
        st.error(
            "현재 식사 기록을 불러올 수 없어요."
        )
        return

    if "past_meals_df" not in st.session_state:
        st.info("아직 식사 기록을 불러오지 않았어요.")
        return

    raw_meals_df = st.session_state[
        "past_meals_df"
    ]

    past_meals = prepare_past_meals(
        raw_meals_df
    )

    if len(past_meals) == 0:
        st.info(
            "지난 7일 동안 기록된 식사가 없습니다."
        )
        return

    st.dataframe(
        past_meals,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 📊 최근 7일 메뉴별 횟수")

    meal_counts = compute_meal_counts(
        past_meals
    )

    meal_count_table = (
        meal_counts
        .reset_index()
    )

    meal_count_table.columns = [
        "메뉴",
        "횟수",
    ]

    st.dataframe(
        meal_count_table,
        use_container_width=True,
        hide_index=True,
    )

    # 현재 선택한 메뉴를 최근 언제 먹었는지 확인
    selected_menu = st.session_state.get(
        "meal_menu",
        MENU_LIST[0],
    )

    selected_history = past_meals[
        past_meals["메뉴"] == selected_menu
    ]

    if len(selected_history) > 0:
        last_date = selected_history["날짜"].max()

        st.caption(
            f"'{selected_menu}'을(를) 최근에 먹은 날: "
            f"{last_date}"
        )
    else:
        st.caption(
            f"최근 7일 동안 '{selected_menu}'을(를) "
            "먹은 기록은 없습니다."
        )


# ----------------------------
# 화면 시작
# ----------------------------

st.title("🍽️ 모두의 점심")

st.write(
    "오늘 점심 메뉴, 함께 골라봐요! "
    "닉네임과 먹고 싶은 메뉴를 선택하고 투표해주세요."
)

st.divider()


# ----------------------------
# 투표 입력
# ----------------------------

if "input_nickname" not in st.session_state:
    st.session_state["input_nickname"] = ""

if "input_menu" not in st.session_state:
    st.session_state["input_menu"] = MENU_LIST[0]


with st.form(
    key="vote_form",
    clear_on_submit=False,
):
    nickname = st.text_input(
        "닉네임을 입력하세요",
        key="input_nickname",
    )

    menu = st.selectbox(
        "먹고 싶은 메뉴를 선택하세요",
        MENU_LIST,
        key="input_menu",
    )

    submitted = st.form_submit_button(
        "투표하기"
    )

    if submitted:
        nickname_clean = nickname.strip()

        if nickname_clean == "":
            st.warning(
                "닉네임을 입력해주세요!"
            )

        else:
            with st.spinner(
                "투표를 저장하는 중..."
            ):
                ok, _ = submit_vote(
                    nickname_clean,
                    menu,
                )

            if ok:
                st.success(
                    f"{nickname_clean}님, "
                    f"'{menu}'에 투표 완료! 🎉"
                )

                # 저장 성공 뒤 즉시 최신 데이터 읽기
                with st.spinner(
                    "최신 결과를 불러오는 중..."
                ):
                    refresh_records()

            else:
                st.error(
                    "투표 저장에 실패했어요. "
                    "잠시 후 다시 시도해주세요."
                )


st.divider()


# ----------------------------
# 새로 읽기
# ----------------------------

refresh_clicked = st.button(
    "🔄 결과 새로 읽기"
)

if refresh_clicked:
    with st.spinner(
        "결과를 불러오는 중..."
    ):
        refresh_records()


# ----------------------------
# 10초 자동 새로고침
# ----------------------------

refresh_count = st_autorefresh(
    interval=10_000,
    key="result_autorefresh",
)

# 최초 실행 또는 자동 새로고침 횟수가 바뀐 경우에만
# Supabase에서 다시 읽는다.
last_refresh_count = st.session_state.get(
    "last_refresh_count"
)

if (
    "today_votes_df" not in st.session_state
    or last_refresh_count != refresh_count
):
    with st.spinner(
        "결과를 불러오는 중..."
    ):
        refresh_records()

    st.session_state[
        "last_refresh_count"
    ] = refresh_count


# ----------------------------
# 결과 / 식사 기록
# ----------------------------

st.divider()

vote_col, meal_col = st.columns(2)

with vote_col:
    render_vote_result_area()

with meal_col:
    render_meal_area()


# 마지막으로 읽은 시각
if "last_read_time" in st.session_state:
    st.caption(
        "마지막으로 읽은 시각: "
        f"{st.session_state['last_read_time']}"
    )
