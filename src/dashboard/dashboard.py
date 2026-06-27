"""
logmon 운영 대시보드
실행: streamlit run dashboard.py
"""

import os
import sys
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]  # src/dashboard/ → 프로젝트 루트
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

DB_PATH = os.getenv("SQLITE_DB_PATH", "./data/logmon.db")

# ── 임계치 ────────────────────────────────────────────────────────────────────
THRESHOLDS = {
    "response_time": 20.0,     # ms
    "busy_threads": 6,
    "exceeded_limit": 0,
    "auth_fail_rate": 0.3,     # 30% 이상이면 경고
}

# ── 페이지 설정 ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="logmon 대시보드",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    [data-testid="stSidebar"] { background-color: #0f1117; }
    .metric-card {
        background: #1a1d27;
        border: 1px solid #2d3149;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 8px;
    }
    .metric-card.warn { border-color: #f59e0b; }
    .metric-card.ok   { border-color: #10b981; }
    .section-title {
        font-size: 13px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #6b7280;
        margin: 24px 0 12px;
    }
</style>
""", unsafe_allow_html=True)


# ── DB 연결 ────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def query(sql: str, params=()) -> pd.DataFrame:
    try:
        return pd.read_sql_query(sql, get_conn(), params=params)
    except Exception as e:
        st.error(f"DB 오류: {e}")
        return pd.DataFrame()


# ── 사이드바 ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛡️ logmon")
    st.markdown("---")
    menu = st.radio(
        "메뉴",
        ["📥 로그 수집", "⚡ 임계치 확인", "📊 로그 조회", "🔍 RAG 검증"],
        label_visibility="collapsed",
    )

# ══════════════════════════════════════════════════════════════════════════════
# 📥 로그 수집
# ══════════════════════════════════════════════════════════════════════════════
if menu == "📥 로그 수집":
    st.title("📥 로그 수집")

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown('<div class="section-title">현재 적재 현황</div>', unsafe_allow_html=True)
        counts = {
            "swg_lib": query("SELECT COUNT(*) AS n FROM log_swg_lib").iloc[0]["n"] if not query("SELECT COUNT(*) AS n FROM log_swg_lib").empty else 0,
            "catalina": query("SELECT COUNT(*) AS n FROM log_catalina").iloc[0]["n"] if not query("SELECT COUNT(*) AS n FROM log_catalina").empty else 0,
            "smps_stats": query("SELECT COUNT(*) AS n FROM log_smps_stats").iloc[0]["n"] if not query("SELECT COUNT(*) AS n FROM log_smps_stats").empty else 0,
        }
        c1, c2, c3 = st.columns(3)
        c1.metric("swg_lib", f"{counts['swg_lib']:,}건")
        c2.metric("catalina", f"{counts['catalina']:,}건")
        c3.metric("smps_stats", f"{counts['smps_stats']:,}건")

    with col2:
        st.markdown('<div class="section-title">수집 실행</div>', unsafe_allow_html=True)
        if st.button("▶ Gmail 수집 실행", use_container_width=True, type="primary"):
            with st.spinner("Gmail에서 로그 수집 중..."):
                result = subprocess.run(
                    ["python", "-m", "src.batch.collect_batch", "--once"],
                    capture_output=True, text=True, cwd=str(ROOT)
                )
                if result.returncode == 0:
                    st.success("수집 완료")
                    st.code(result.stdout)
                    get_conn.clear()
                    st.rerun()
                else:
                    st.error("수집 실패")
                    st.code(result.stderr)

    # 최근 수집 메일 목록
    st.markdown('<div class="section-title">최근 수집 메일</div>', unsafe_allow_html=True)
    df_mail = query("SELECT id, subject, date FROM log_emails ORDER BY date DESC LIMIT 20")
    if not df_mail.empty:
        st.dataframe(df_mail, use_container_width=True, hide_index=True)
    else:
        st.info("수집된 메일이 없습니다.")


# ══════════════════════════════════════════════════════════════════════════════
# ⚡ 임계치 확인
# ══════════════════════════════════════════════════════════════════════════════
elif menu == "⚡ 임계치 확인":
    st.title("⚡ 임계치 확인")

    # smps_stats 최근 10분 평균
    st.markdown('<div class="section-title">smps_stats 성능 지표 (최근 10분 평균, 호스트별)</div>', unsafe_allow_html=True)
    df_smps = query("""
        SELECT host,
               ROUND(AVG(response_time), 2) AS avg_response_time,
               ROUND(AVG(busy_threads), 2)  AS avg_busy_threads,
               MAX(exceeded_limit)          AS max_exceeded_limit,
               MAX(core_result)             AS core_result,
               COUNT(*)                     AS sample_count,
               MAX(timestamp)               AS last_timestamp
        FROM log_smps_stats
        WHERE timestamp >= datetime('now', '-10 minutes', 'localtime')
        GROUP BY host
        ORDER BY host
    """)

    if not df_smps.empty:
        for _, row in df_smps.iterrows():
            rt_warn = float(row["avg_response_time"]) > THRESHOLDS["response_time"]
            bt_warn = float(row["avg_busy_threads"]) >= THRESHOLDS["busy_threads"]
            el_warn = int(row["max_exceeded_limit"]) > THRESHOLDS["exceeded_limit"]
            any_warn = rt_warn or bt_warn or el_warn
            card_cls = "warn" if any_warn else "ok"
            icon = "⚠️" if any_warn else "✅"

            st.markdown(f"""
            <div class="metric-card {card_cls}">
                {icon} <b>{row['host']}</b> &nbsp;|&nbsp;
                최근 10분 평균 ({row['sample_count']}개 샘플) &nbsp;|&nbsp; 마지막: {row['last_timestamp']}<br>
                Response Time: <b>{row['avg_response_time']} ms</b>
                {'🔴' if rt_warn else ''} &nbsp;|&nbsp;
                Busy Threads: <b>{row['avg_busy_threads']}</b>
                {'🔴' if bt_warn else ''} &nbsp;|&nbsp;
                Exceeded Limit(max): <b>{row['max_exceeded_limit']}</b>
                {'🔴' if el_warn else ''} &nbsp;|&nbsp;
                Core Result: <b>{row['core_result']}</b>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("최근 10분 내 smps_stats 데이터가 없습니다.")

    # swg_lib 인증 실패율
    st.markdown('<div class="section-title">swg_lib 인증 실패율 (호스트별)</div>', unsafe_allow_html=True)
    df_auth = query("""
        SELECT host,
               COUNT(*) AS total,
               SUM(CASE WHEN auth_result = -1 THEN 1 ELSE 0 END) AS fail,
               ROUND(100.0 * SUM(CASE WHEN auth_result = -1 THEN 1 ELSE 0 END) / COUNT(*), 1) AS fail_rate
        FROM log_swg_lib
        GROUP BY host
        ORDER BY fail_rate DESC
    """)
    if not df_auth.empty:
        st.dataframe(df_auth, use_container_width=True, hide_index=True)
    else:
        st.info("swg_lib 데이터가 없습니다.")

    # 임계치 설정값 표시
    st.markdown('<div class="section-title">현재 임계치 설정</div>', unsafe_allow_html=True)
    df_th = pd.DataFrame([
        {"항목": "Response Time", "임계치": f"> {THRESHOLDS['response_time']} ms"},
        {"항목": "Busy Threads", "임계치": f">= {THRESHOLDS['busy_threads']}"},
        {"항목": "Exceeded Limit", "임계치": f"> {THRESHOLDS['exceeded_limit']}"},
        {"항목": "Auth Fail Rate", "임계치": f"> {int(THRESHOLDS['auth_fail_rate']*100)}%"},
    ])
    st.dataframe(df_th, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# 📊 로그 조회
# ══════════════════════════════════════════════════════════════════════════════
elif menu == "📊 로그 조회":
    st.title("📊 로그 조회")

    log_type = st.selectbox("로그 타입", ["smps_stats", "swg_lib", "catalina"])

    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("시작일", value=datetime.now().date() - timedelta(days=7))
    with col2:
        date_to = st.date_input("종료일", value=datetime.now().date())

    hosts = query("SELECT DISTINCT host FROM log_swg_lib ORDER BY host")
    host_options = ["전체"] + (hosts["host"].tolist() if not hosts.empty else [])
    selected_host = st.selectbox("호스트", host_options)
    host_filter = "" if selected_host == "전체" else f"AND host = '{selected_host}'"

    if log_type == "smps_stats":
        df = query(f"""
            SELECT timestamp, host, response_time, busy_threads,
                   throughput, exceeded_limit, core_result, current_connections
            FROM log_smps_stats
            WHERE timestamp >= '{date_from}' AND timestamp <= '{date_to} 23:59:59'
            {host_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            df_chart = df[["timestamp", "host", "response_time", "busy_threads"]].copy()
            df_chart["timestamp"] = pd.to_datetime(df_chart["timestamp"])
            df_chart = df_chart.sort_values("timestamp")

            # 10분 평균 집계
            df_chart["bucket"] = df_chart["timestamp"].dt.floor("10min")
            df_10m = df_chart.groupby(["bucket", "host"]).agg(
                response_time=("response_time", "mean"),
                busy_threads=("busy_threads", "mean"),
            ).reset_index()

            # 시간대별 Response Time 차트 (10분 평균)
            st.markdown('<div class="section-title">Response Time 10분 평균 (ms)</div>', unsafe_allow_html=True)
            df_rt_pivot = df_10m.pivot_table(index="bucket", columns="host", values="response_time")
            st.line_chart(df_rt_pivot)

            # 시간대별 Busy Threads 차트 (10분 평균)
            st.markdown('<div class="section-title">Busy Threads 10분 평균</div>', unsafe_allow_html=True)
            df_bt_pivot = df_10m.pivot_table(index="bucket", columns="host", values="busy_threads")
            st.line_chart(df_bt_pivot)

            st.markdown('<div class="section-title">원본 데이터</div>', unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif log_type == "swg_lib":
        df = query(f"""
            SELECT timestamp, host, auth_type, auth_result, auth_reason,
                   user_id, co_cl_cd
            FROM log_swg_lib
            WHERE timestamp >= '{date_from}' AND timestamp <= '{date_to} 23:59:59'
            {host_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            # 시간대별 인증 성공/실패 추이
            st.markdown('<div class="section-title">시간대별 인증 결과</div>', unsafe_allow_html=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["hour"] = df["timestamp"].dt.floor("h")
            df_grouped = df.groupby(["hour", "auth_result"]).size().unstack(fill_value=0)
            df_grouped.columns = [f"result_{c}" for c in df_grouped.columns]
            st.bar_chart(df_grouped)

            st.markdown('<div class="section-title">원본 데이터</div>', unsafe_allow_html=True)
            st.dataframe(df, use_container_width=True, hide_index=True)

    elif log_type == "catalina":
        df = query(f"""
            SELECT timestamp, host, log_level, logger, log_message
            FROM log_catalina
            WHERE timestamp >= '{date_from}' AND timestamp <= '{date_to} 23:59:59'
            {host_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            # 로그 레벨 필터
            levels = ["전체"] + sorted(df["log_level"].dropna().unique().tolist())
            selected_level = st.selectbox("로그 레벨", levels)
            if selected_level != "전체":
                df = df[df["log_level"] == selected_level]

            st.dataframe(df, use_container_width=True, hide_index=True)

    if df.empty:
        st.info("조회된 데이터가 없습니다.")


# ══════════════════════════════════════════════════════════════════════════════
# 🔍 RAG 검증
# ══════════════════════════════════════════════════════════════════════════════
elif menu == "🔍 RAG 검증":
    st.title("🔍 RAG 검증")

    query_text = st.text_input("검색어 (한국어/영어 모두 가능)", placeholder="예: 세션풀 고갈, Busy_Threads threshold")
    top_k = st.slider("결과 수", min_value=1, max_value=10, value=5)
    source = st.selectbox("검색 대상", ["all", "manual", "incident_history"])

    if st.button("검색", type="primary") and query_text:
        with st.spinner("검색 중..."):
            try:
                from src.tools.rag_search_tool import rag_search_tool, SourceFilter
                result = rag_search_tool(
                    query=query_text,
                    top_k=top_k,
                    source_filter=SourceFilter(source),
                )
                translated = result.get("translated_query", "")
                if translated and translated != query_text:
                    st.info(f"번역된 쿼리: **{translated}**")

                results = result.get("results", [])
                if results:
                    for i, r in enumerate(results, 1):
                        source_label = "📖 매뉴얼" if r["source"] == "siteminder_manual" else "📋 장애이력"
                        with st.expander(
                            f"[{i}] {source_label} | {r['heading']} (p.{r['page_start']}) | 유사도: {r['score']}",
                            expanded=(i == 1),
                        ):
                            st.text(r["content"][:800])
                else:
                    st.warning("검색 결과가 없습니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")