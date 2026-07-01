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
KST_OFFSET = timedelta(hours=9)


def to_kst(series: "pd.Series") -> "pd.Series":
    """UTC timestamp 시리즈를 KST로 변환 (tz 제거하여 naive datetime 반환)"""
    dt = pd.to_datetime(series, format="ISO8601", utc=True)
    return (dt + KST_OFFSET).dt.tz_localize(None)
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
        def get_range(table):
            df = query(f"SELECT MIN(timestamp) AS s, MAX(timestamp) AS e, COUNT(*) AS n FROM {table}")
            if df.empty: return "-", "-", 0
            return df.iloc[0]["s"], df.iloc[0]["e"], int(df.iloc[0]["n"])

        def fmt_num(n): return f"{int(n):,}" if n else "0"
        for tbl, label in [("log_swg_lib","swg_lib"),("log_catalina","catalina"),("log_smps_stats","smps_stats")]:
            s, e, n = get_range(tbl)
            s_kst = (pd.to_datetime(s, format="ISO8601", utc=True) + KST_OFFSET).strftime("%Y-%m-%d %H:%M") if s != "-" else "-"
            e_kst = (pd.to_datetime(e, format="ISO8601", utc=True) + KST_OFFSET).strftime("%Y-%m-%d %H:%M") if e != "-" else "-"
            st.markdown(f"""
            <div class="metric-card ok">
                <b>{label}</b> &nbsp;|&nbsp; {fmt_num(n)}건<br>
                <small>시작: {s_kst} &nbsp;|&nbsp; 종료: {e_kst} (KST)</small>
            </div>
            """, unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="section-title">수집 실행</div>', unsafe_allow_html=True)
        if st.button("▶ Gmail 수집 실행", width="stretch", type="primary"):
            with st.spinner("Gmail에서 로그 수집 중..."):
                import sys, time as _time
                env = os.environ.copy()
                env["PYTHONPATH"] = str(ROOT)
                _start = _time.time()
                _start_kst = (datetime.now() + KST_OFFSET).strftime("%Y-%m-%d %H:%M:%S")

                # 1. 메일 수집
                r1 = subprocess.run(
                    [sys.executable, "-m", "src.batch.collect_batch"],
                    capture_output=True, text=True, cwd=str(ROOT), env=env
                )
                # 2. 로그 파싱
                r2 = subprocess.run(
                    [sys.executable, "-m", "src.tools.log_parser"],
                    capture_output=True, text=True, cwd=str(ROOT), env=env
                )
                _elapsed = round(_time.time() - _start, 1)

                if r1.returncode == 0 and r2.returncode == 0:
                    st.success(f"수집 및 파싱 완료 | 수행 시각: {_start_kst} KST | 소요: {_elapsed}초")
                    st.code(r1.stdout + r2.stdout)
                    get_conn.clear()
                    st.rerun()
                else:
                    st.error("수집/파싱 실패")
                    st.code(r1.stderr + r2.stderr)

    # 최근 수집 메일 — 종류별 3개씩
    st.markdown('<div class="section-title">최근 수집 메일 (종류별 최근 3건)</div>', unsafe_allow_html=True)
    df_mail = query("SELECT id, subject, date FROM log_emails ORDER BY id DESC LIMIT 200")
    if not df_mail.empty:
        import re
        def extract_log_type(subject):
            if "SWG_LIB" in subject or "swg_lib" in subject.lower(): return "swg_lib"
            if "Catalina" in subject or "catalina" in subject.lower(): return "catalina"
            if "SMPS" in subject or "smps" in subject.lower(): return "smps_stats"
            return "기타"

        def extract_log_date(subject):
            # "Thu 25 Jun 8:00AM KST" 패턴 추출
            m = re.search(r"\|\s*(.+?)\s*$", subject)
            return m.group(1).strip() if m else "-"

        df_mail["log_type"] = df_mail["subject"].apply(extract_log_type)
        df_mail["log_date"] = df_mail["subject"].apply(extract_log_date)

        rows = []
        for log_type in ["swg_lib", "catalina", "smps_stats"]:
            top3 = df_mail[df_mail["log_type"] == log_type].head(3)
            rows.append(top3)

        df_show = pd.concat(rows)[["id", "log_type", "log_date", "date"]].rename(
            columns={"log_type": "종류", "log_date": "로그 기준일자", "date": "수집일시"}
        )
        st.dataframe(df_show, width="stretch", hide_index=True)
    else:
        st.info("수집된 메일이 없습니다.")


# ══════════════════════════════════════════════════════════════════════════════
# ⚡ 임계치 확인
# ══════════════════════════════════════════════════════════════════════════════
elif menu == "⚡ 임계치 확인":
    st.title("⚡ 임계치 확인")

    # 상태 판단 함수
    import json as _json3
    _profile3 = {}
    _tp3_path = ROOT / "data" / "threshold_profile.json"
    if _tp3_path.exists():
        with open(_tp3_path, encoding="utf-8") as _f3:
            _profile3 = _json3.load(_f3)

    def _auth_status(host, fail_rate, wd, bk):
        try:
            af = _profile3["hosts"][host][wd][bk]["auth_fail_rate"]
            if fail_rate >= af["critical_threshold"]: return "🔴 즉시조치"
            if fail_rate >= af["monitor_threshold"]: return "⚠️ 모니터링"
            return "✅ 정상"
        except: return "-"

    def _otp_status(host, fail_rate, wd, bk):
        try:
            otp = _profile3["hosts"][host][wd][bk]["otp_success_rate"]
            if otp.get("critical_threshold") and fail_rate >= otp["critical_threshold"]: return "🔴 즉시조치"
            if otp.get("monitor_threshold") and fail_rate >= otp["monitor_threshold"]: return "⚠️ 모니터링"
            return "✅ 정상"
        except: return "-"


    st.markdown('---')
    df_latest_ts = query("SELECT MAX(timestamp) AS t FROM log_smps_stats")
    latest_label = ''
    if not df_latest_ts.empty and df_latest_ts.iloc[0]['t']:
        _lt = (pd.to_datetime(df_latest_ts.iloc[0]['t'], format='ISO8601', utc=True) + KST_OFFSET)
        latest_label = f' | 최신 수집: {_lt.strftime("%Y-%m-%d %H:%M")} KST'
    st.subheader(f'📊 SiteMinder 성능 지표 (최신 수집 기준 10분){latest_label}')
    # 최신 수집 시점 조회
    df_latest = query("SELECT MAX(timestamp) AS latest FROM log_smps_stats")
    latest_ts = df_latest.iloc[0]["latest"] if not df_latest.empty else None

    df_smps = query("""
        SELECT host,
               ROUND(AVG(response_time), 2) AS avg_response_time,
               ROUND(AVG(busy_threads), 2)  AS avg_busy_threads,
               MAX(exceeded_limit)          AS max_exceeded_limit,
               MAX(core_result)             AS core_result,
               COUNT(*)                     AS sample_count,
               MAX(timestamp)               AS last_timestamp
        FROM log_smps_stats
        WHERE timestamp >= datetime((SELECT MAX(timestamp) FROM log_smps_stats), '-10 minutes')
        GROUP BY host
        ORDER BY host
    """) if latest_ts else pd.DataFrame()

    # 임계치 프로파일 로드
    import json as _json
    _profile = {}
    _profile_path = ROOT / "data" / "threshold_profile.json"
    if _profile_path.exists():
        with open(_profile_path, encoding="utf-8") as _f:
            _profile = _json.load(_f)

    def _get_threshold(host, weekday, bucket, metric, level):
        try:
            return _profile["hosts"][host][weekday][bucket][metric][level]
        except (KeyError, TypeError):
            return None

    if not df_smps.empty:
        from datetime import timezone as _tz
        _wd_map = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
        # 현재 시각이 아닌 최신 로그 timestamp 기준으로 버킷 계산
        if latest_ts:
            _log_dt = (pd.to_datetime(latest_ts, format="ISO8601", utc=True) + KST_OFFSET)
        else:
            _log_dt = datetime.now(_tz.utc) + KST_OFFSET
        _cur_wd = _wd_map[_log_dt.weekday()]
        _cur_bk = f"{_log_dt.hour:02d}:{(_log_dt.minute//10)*10:02d}"

        for _, row in df_smps.iterrows():
            host = row["host"]
            rt_mon = _get_threshold(host, _cur_wd, _cur_bk, "response_time", "monitor_threshold")
            bt_mon = _get_threshold(host, _cur_wd, _cur_bk, "busy_threads", "monitor_threshold")
            rt_crit = _get_threshold(host, _cur_wd, _cur_bk, "response_time", "critical_threshold")
            bt_crit = _get_threshold(host, _cur_wd, _cur_bk, "busy_threads", "critical_threshold")

            rt_val = float(row["avg_response_time"])
            bt_val = float(row["avg_busy_threads"])
            el_val = int(row["max_exceeded_limit"])

            rt_warn = rt_mon and rt_val > rt_mon
            bt_warn = bt_mon and bt_val > bt_mon
            rt_crit_warn = rt_crit and rt_val > rt_crit
            bt_crit_warn = bt_crit and bt_val > bt_crit
            el_warn = el_val > THRESHOLDS["exceeded_limit"]

            any_warn = rt_warn or bt_warn or el_warn
            any_crit = rt_crit_warn or bt_crit_warn
            card_cls = "warn" if any_crit else ("warn" if any_warn else "ok")
            icon = "🔴" if any_crit else ("⚠️" if any_warn else "✅")

            rt_icon = "🔴" if rt_crit_warn else ("⚠️" if rt_warn else "")
            bt_icon = "🔴" if bt_crit_warn else ("⚠️" if bt_warn else "")

            last_kst = (pd.to_datetime(row["last_timestamp"], format="ISO8601", utc=True) + KST_OFFSET).strftime("%H:%M") if row["last_timestamp"] else "-"

            st.markdown(f"""
            <div class="metric-card {card_cls}">
                {icon} <b>{host}</b> &nbsp;|&nbsp;
                최신 수집 기준 10분 ({row['sample_count']}개 샘플) &nbsp;|&nbsp; 마지막: {last_kst} KST<br>
                Response Time: <b>{rt_val} ms</b> {rt_icon} &nbsp;|&nbsp;
                Busy Threads: <b>{bt_val}</b> {bt_icon} &nbsp;|&nbsp;
                Exceeded Limit: <b>{el_val}</b> {'🔴' if el_warn else ''} &nbsp;|&nbsp;
                Core Result: <b>{row['core_result']}</b>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("smps_stats 데이터가 없습니다.")

    st.markdown('---')
    # 최신 수집 시각 기준
    df_latest_auth = query("SELECT MAX(timestamp) AS t FROM log_swg_lib")
    _auth_latest = df_latest_auth.iloc[0]["t"] if not df_latest_auth.empty else None
    _auth_label = ""
    if _auth_latest:
        _at = (pd.to_datetime(_auth_latest, format="ISO8601", utc=True) + KST_OFFSET)
        _at_from = _at - pd.Timedelta(minutes=10)
        _auth_label = f" | {_at_from.strftime('%Y-%m-%d %H:%M')} ~ {_at.strftime('%H:%M')} KST"
    st.subheader(f'🔐 1차 인증 현황{_auth_label}')
    df_auth = query("""
        SELECT host,
               COUNT(*) AS total,
               SUM(CASE WHEN auth_result = 0 THEN 1 ELSE 0 END) AS success,
               ROUND(100.0 * SUM(CASE WHEN auth_result = 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS success_rate
        FROM log_swg_lib
        WHERE auth_type = 'PWD'
        AND timestamp >= datetime((SELECT MAX(timestamp) FROM log_swg_lib), '-10 minutes')
        GROUP BY host
        ORDER BY success_rate ASC
    """)
    if not df_auth.empty:
        # 최신 로그 기준 요일/버킷
        _wd_map2 = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
        if _auth_latest:
            _al = pd.to_datetime(_auth_latest, format="ISO8601", utc=True) + KST_OFFSET
            _auth_wd = _wd_map2[_al.weekday()]
            _auth_bk = f"{_al.hour:02d}:{(_al.minute//10)*10:02d}"
        else:
            _auth_wd, _auth_bk = "mon", "00:00"

        df_auth["fail_rate"] = 100.0 - df_auth["success_rate"]
        df_auth["상태"] = df_auth.apply(
            lambda r: _auth_status(r["host"], r["fail_rate"], _auth_wd, _auth_bk), axis=1
        )
        df_auth_show = df_auth[["상태","host","total","success","success_rate"]].rename(columns={
            "host": "호스트",
            "total": "총 시도",
            "success": "성공",
            "success_rate": "1차 인증 성공률(%)"
        })
        for col in ["총 시도", "성공"]:
            df_auth_show[col] = df_auth_show[col].apply(lambda x: f"{int(x):,}")
        st.dataframe(df_auth_show, width="stretch", hide_index=True)
    else:
        st.info("swg_lib 데이터가 없습니다.")

    st.markdown('---')
    # 2차 인증 현황
    df_latest_cat = query("SELECT MAX(timestamp) AS t FROM log_catalina")
    _cat_latest = df_latest_cat.iloc[0]["t"] if not df_latest_cat.empty else None
    _cat_label = ""
    if _cat_latest:
        _ct = (pd.to_datetime(_cat_latest, format="ISO8601", utc=True) + KST_OFFSET)
        _ct_from = _ct - pd.Timedelta(minutes=10)
        _cat_label = f" | {_ct_from.strftime('%Y-%m-%d %H:%M')} ~ {_ct.strftime('%H:%M')} KST"
    st.subheader(f'📱 2차 인증 현황{_cat_label}')

    df_cat = query("""
        SELECT host,
               SUM(CASE WHEN log_message LIKE '%Request OTP Generate%' THEN 1 ELSE 0 END) AS otp_send_try,
               SUM(CASE WHEN log_message LIKE '%Verification result = [true]%' THEN 1 ELSE 0 END) AS otp_success,
               SUM(CASE WHEN log_message LIKE '%Verification result = [false]%' THEN 1 ELSE 0 END) AS otp_fail
        FROM log_catalina
        WHERE timestamp >= datetime((SELECT MAX(timestamp) FROM log_catalina), '-10 minutes')
        GROUP BY host
        ORDER BY host
    """)
    if not df_cat.empty:
        _wd_map3 = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
        if _cat_latest:
            _cl = pd.to_datetime(_cat_latest, format="ISO8601", utc=True) + KST_OFFSET
            _cat_wd = _wd_map3[_cl.weekday()]
            _cat_bk = f"{_cl.hour:02d}:{(_cl.minute//10)*10:02d}"
        else:
            _cat_wd, _cat_bk = "mon", "00:00"

        df_cat["otp_success_rate"] = df_cat.apply(
            lambda r: round(100.0 * r["otp_success"] / r["otp_send_try"], 1) if r["otp_send_try"] > 0 else None, axis=1
        )
        df_cat["otp_fail_rate"] = df_cat.apply(
            lambda r: round(100.0 * r["otp_fail"] / r["otp_send_try"], 1) if r["otp_send_try"] > 0 else 0.0, axis=1
        )
        df_cat["상태"] = df_cat.apply(
            lambda r: _otp_status(r["host"], r["otp_fail_rate"], _cat_wd, _cat_bk), axis=1
        )
        df_cat_show = df_cat[["상태","host","otp_send_try","otp_success","otp_fail","otp_success_rate"]].rename(columns={
            "host": "호스트",
            "otp_send_try": "OTP 발송 시도",
            "otp_success": "OTP 인증 성공",
            "otp_fail": "OTP 인증 실패",
            "otp_success_rate": "OTP 인증 성공률(%)",
        })
        for col in ["OTP 발송 시도", "OTP 인증 성공", "OTP 인증 실패"]:
            df_cat_show[col] = df_cat_show[col].apply(lambda x: f"{int(x):,}")
        st.dataframe(df_cat_show, width="stretch", hide_index=True)
    else:
        st.info("catalina 데이터가 없습니다.")

    st.markdown('---')
    st.subheader('🎯 LLM 생성 임계치 프로파일')
    profile_path = ROOT / "data" / "threshold_profile.json"
    if profile_path.exists():
        import json
        with open(profile_path, encoding="utf-8") as f:
            tp = json.load(f)

        _gen_utc = tp.get('generated_at', '')
        _gen_kst = (pd.to_datetime(_gen_utc, utc=True) + KST_OFFSET).strftime("%Y-%m-%d %H:%M") if _gen_utc else '-'
        _method = tp.get('method', '-')
        st.caption(f"기준 기간: {tp.get('baseline_period', '-')} | 생성: {_gen_kst} KST")

        if tp.get('analysis_summary'):
            _summary = tp['analysis_summary']
            import re as _re
            _sentences = [s.strip() for s in _re.split(r"(?<=[.]) +", _summary) if s.strip()]
            _emojis = ["📌","📈","⚡","🔍","💡","📋"]
            _bullet_lines = ["**📝 분석 요약**"] + [f"{_emojis[i % len(_emojis)]} {s}" for i, s in enumerate(_sentences)]
            st.markdown("  \n".join(_bullet_lines))

        # 최신 로그 timestamp 기준 버킷 선택
        from datetime import timezone
        weekday_map = {0:"mon",1:"tue",2:"wed",3:"thu",4:"fri",5:"sat",6:"sun"}
        weekday_kor = {"mon":"월요일","tue":"화요일","wed":"수요일","thu":"목요일","fri":"금요일","sat":"토요일","sun":"일요일"}
        _df_latest_smps = query("SELECT MAX(timestamp) AS t FROM log_smps_stats")
        _latest_smps = _df_latest_smps.iloc[0]["t"] if not _df_latest_smps.empty else None
        if _latest_smps:
            _log_kst = pd.to_datetime(_latest_smps, format="ISO8601", utc=True) + KST_OFFSET
        else:
            _log_kst = datetime.now(timezone.utc) + KST_OFFSET
        cur_weekday = weekday_map[_log_kst.weekday()]
        cur_bucket = f"{_log_kst.hour:02d}:{(_log_kst.minute//10)*10:02d}"

        col_wd, col_bk = st.columns(2)
        with col_wd:
            weekdays = list(weekday_map.values())
            weekday_labels = [weekday_kor[w] for w in weekdays]
            cur_idx = weekdays.index(cur_weekday)
            sel_label = st.selectbox("요일", weekday_labels, index=cur_idx)
            sel_weekday = weekdays[weekday_labels.index(sel_label)]
        with col_bk:
            buckets = [f"{h:02d}:{m:02d}" for h in range(24) for m in range(0,60,10)]
            sel_bucket = st.selectbox("시간대", buckets, index=buckets.index(cur_bucket) if cur_bucket in buckets else 0)

        hosts_data = tp.get("hosts", {})
        if hosts_data:
            rt_rows, bt_rows, af_rows, otp_rows = [], [], [], []
            for host in sorted(hosts_data.keys()):
                b = hosts_data[host].get(sel_weekday, {}).get(sel_bucket, {})
                if not b:
                    continue
                rt = b.get("response_time", {})
                bt = b.get("busy_threads", {})
                af = b.get("auth_fail_rate", {})
                def _v(d, k): return d.get(k) if d.get(k) is not None else "-"
                rt_rows.append({"호스트": host, "정상 기준(ms)": _v(rt,"baseline_avg"), "모니터링 필요(ms)": _v(rt,"monitor_threshold"), "즉시조치 필요(ms)": _v(rt,"critical_threshold")})
                bt_rows.append({"호스트": host, "정상 기준": _v(bt,"baseline_avg"), "모니터링 필요": _v(bt,"monitor_threshold"), "즉시조치 필요": _v(bt,"critical_threshold")})
                af_rows.append({"호스트": host, "정상 기준(%)": _v(af,"baseline_avg"), "모니터링 필요(%)": _v(af,"monitor_threshold"), "즉시조치 필요(%)": _v(af,"critical_threshold")})
                otp = b.get("otp_success_rate", {})
                if otp.get("baseline_avg") is not None:
                    otp_rows.append({"호스트": host, "정상 성공률(%)": _v(otp,"baseline_avg"), "실패율 모니터링(%)": _v(otp,"monitor_threshold"), "실패율 즉시조치(%)": _v(otp,"critical_threshold")})

            if rt_rows:
                st.markdown("**⏱ 응답시간 (Response Time, ms)**")
                st.dataframe(pd.DataFrame(rt_rows), width="stretch", hide_index=True)
                st.markdown("**🔄 BusyThreads**")
                st.dataframe(pd.DataFrame(bt_rows), width="stretch", hide_index=True)
                st.markdown("**🔐 1차 인증 실패율 (%)**")
                st.dataframe(pd.DataFrame(af_rows), width="stretch", hide_index=True)
                if otp_rows:
                    st.markdown("**📱 2차 인증 OTP 성공률 (%)**")
                    st.dataframe(pd.DataFrame(otp_rows), width="stretch", hide_index=True)
            else:
                st.warning(f"{sel_weekday} {sel_bucket} 버킷 데이터 없음")

        # 산출 방법 설명
        st.markdown(f"""
ℹ️ **산출 방법**
- 📅 기준 기간: {tp.get('baseline_period', '-')} 데이터 사용
- 🧹 IQR 방식으로 이상치 제거 (Q1-1.5×IQR ~ Q3+1.5×IQR 범위 외 제외)
- 📊 정상 기준값: p50 (중앙값)
- ⚠️ 모니터링 필요: p95 × 1.5 초과 시
- 🔴 즉시조치 필요: p95 × 2.0 초과 시
- 🔁 주 1회 갱신 예정 (데이터 축적 후 임계치 범위 재조정 예정)
""")
    else:
        st.warning("임계치 프로파일 없음. `python -m src.scripts.generate_threshold_profile` 실행 필요")


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

    col_host, col_toggle = st.columns([3, 1])
    with col_host:
        selected_host = st.selectbox("호스트", host_options)
    with col_toggle:
        sample_only = st.toggle("샘플 데이터만", value=False)

    host_filter = "" if selected_host == "전체" else f"AND host = '{selected_host}'"
    sample_filter = "AND email_id IN (9001, 9002, 9999)" if sample_only else ""

    do_query = st.button("🔍 조회", type="primary")

    if do_query and log_type == "smps_stats":
        df = query(f"""
            SELECT timestamp, host, response_time, busy_threads,
                   throughput, exceeded_limit, core_result, current_connections
            FROM log_smps_stats
            WHERE timestamp >= '{date_from}T00:00:00.000Z' AND timestamp <= '{date_to}T23:59:59.999Z'
            {host_filter} {sample_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            df_chart = df[["timestamp", "host", "response_time", "busy_threads"]].copy()
            df_chart["timestamp"] = to_kst(df_chart["timestamp"])
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
            st.dataframe(df, width="stretch", hide_index=True)

    elif do_query and log_type == "swg_lib":
        df = query(f"""
            SELECT timestamp, host, auth_type, auth_result, auth_reason,
                   user_id, co_cl_cd
            FROM log_swg_lib
            WHERE timestamp >= '{date_from}T00:00:00.000Z' AND timestamp <= '{date_to}T23:59:59.999Z'
            {host_filter} {sample_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            # 시간대별 인증 성공/실패 추이
            st.markdown('<div class="section-title">시간대별 인증 결과</div>', unsafe_allow_html=True)
            df["timestamp"] = to_kst(df["timestamp"])
            df["hour"] = df["timestamp"].dt.floor("h")
            df_grouped = df.groupby(["hour", "auth_result"]).size().unstack(fill_value=0)
            df_grouped.columns = [f"result_{c}" for c in df_grouped.columns]
            st.bar_chart(df_grouped)

            st.markdown('<div class="section-title">원본 데이터</div>', unsafe_allow_html=True)
            st.dataframe(df, width="stretch", hide_index=True)

    elif do_query and log_type == "catalina":
        df = query(f"""
            SELECT timestamp, host, log_level, logger, log_message
            FROM log_catalina
            WHERE timestamp >= '{date_from}T00:00:00.000Z' AND timestamp <= '{date_to}T23:59:59.999Z'
            {host_filter} {sample_filter}
            ORDER BY timestamp DESC
            LIMIT 500
        """)
        if not df.empty:
            # 로그 레벨 필터
            levels = ["전체"] + sorted(df["log_level"].dropna().unique().tolist())
            selected_level = st.selectbox("로그 레벨", levels)
            if selected_level != "전체":
                df = df[df["log_level"] == selected_level]

            st.dataframe(df, width="stretch", hide_index=True)

    elif do_query:
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