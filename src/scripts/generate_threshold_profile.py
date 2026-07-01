"""
임계치 프로파일 생성 스크립트 (주 1회 실행)
- 기준 기간: 6/22~6/28 (또는 --start/--end 인자로 지정)
- IQR 이상치 제거 후 p50/p95 기반 임계치 계산 (Python 직접 계산)
- 요일 × 호스트 × 10분 버킷 단위 프로파일 생성
- LLM은 전체 분석 요약 1회만 사용
- 저장 경로: data/threshold_profile.json

실행:
    python -m src.scripts.generate_threshold_profile
    python -m src.scripts.generate_threshold_profile --start 2026-06-22 --end 2026-06-28
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from dotenv import load_dotenv
from openai import AzureOpenAI
import pandas as pd

load_dotenv()

DB_PATH = os.getenv("SQLITE_DB_PATH")
OUTPUT_PATH = "./data/threshold_profile.json"

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")

WEEKDAY_MAP = {"0": "sun", "1": "mon", "2": "tue", "3": "wed", "4": "thu", "5": "fri", "6": "sat"}


def _remove_outliers_iqr(series: pd.Series) -> pd.Series:
    """IQR 방식 이상치 제거 (Q1-1.5xIQR ~ Q3+1.5xIQR)"""
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    return series[(series >= q1 - 1.5 * iqr) & (series <= q3 + 1.5 * iqr)]


def _calc_thresholds(series: pd.Series) -> dict:
    """p50/p95 기반 임계치 계산"""
    clean = _remove_outliers_iqr(series)
    if clean.empty:
        clean = series
    p50 = round(float(clean.quantile(0.50)), 3)
    p95 = round(float(clean.quantile(0.95)), 3)
    return {
        "baseline_avg": p50,
        "normal_max": p95,
        "monitor_threshold": round(p95 * 1.5, 3),
        "critical_threshold": round(p95 * 2.0, 3),
    }


def fetch_smps_stats(start: str, end: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT
            host,
            strftime('%w', datetime(timestamp, '+9 hours')) AS weekday,
            strftime('%H', datetime(timestamp, '+9 hours')) || ':' ||
            printf('%02d', CAST(strftime('%M', datetime(timestamp, '+9 hours')) AS INTEGER) / 10 * 10) AS bucket,
            response_time, busy_threads, throughput, exceeded_limit
        FROM log_smps_stats
        WHERE timestamp >= ? AND timestamp <= ?
    """, conn, params=(f"{start}T00:00:00.000Z", f"{end}T23:59:59.999Z"))
    conn.close()
    df["weekday"] = df["weekday"].map(WEEKDAY_MAP)
    return df


def fetch_auth_stats(start: str, end: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT
            host,
            strftime('%w', datetime(timestamp, '+9 hours')) AS weekday,
            strftime('%H', datetime(timestamp, '+9 hours')) || ':' ||
            printf('%02d', CAST(strftime('%M', datetime(timestamp, '+9 hours')) AS INTEGER) / 10 * 10) AS bucket,
            auth_result
        FROM log_swg_lib
        WHERE timestamp >= ? AND timestamp <= ?
    """, conn, params=(f"{start}T00:00:00.000Z", f"{end}T23:59:59.999Z"))
    conn.close()
    df["weekday"] = df["weekday"].map(WEEKDAY_MAP)
    df["fail"] = (df["auth_result"] == -1).astype(int)
    return df


def build_profile(smps_df: pd.DataFrame, auth_df: pd.DataFrame, otp_df: pd.DataFrame = None) -> dict:
    """host × weekday × bucket 단위 임계치 계산"""
    hosts_result = {}

    for host in sorted(smps_df["host"].unique()):
        hosts_result[host] = {}
        for weekday in sorted(smps_df["weekday"].unique()):
            hosts_result[host][weekday] = {}
            smps_hw = smps_df[(smps_df["host"] == host) & (smps_df["weekday"] == weekday)]
            auth_hw = auth_df[(auth_df["host"] == host) & (auth_df["weekday"] == weekday)]

            all_buckets = sorted(smps_hw["bucket"].unique())
            for bucket in all_buckets:
                smps_b = smps_hw[smps_hw["bucket"] == bucket]
                auth_b = auth_hw[auth_hw["bucket"] == bucket]

                # 인증 실패율 계산 (10분 버킷 전체 실패율)
                if len(auth_b) > 0:
                    fail_rate = round(auth_b["fail"].mean() * 100, 3)
                    af_thresholds = {
                        "baseline_avg": fail_rate,
                        "normal_max": round(fail_rate * 1.0, 3),
                        "monitor_threshold": round(fail_rate * 1.5, 3),
                        "critical_threshold": round(fail_rate * 2.0, 3),
                    }
                else:
                    af_thresholds = {"baseline_avg": 0, "normal_max": 0,
                                     "monitor_threshold": 0, "critical_threshold": 0}

                # OTP 성공률 임계치
                if otp_df is not None:
                    otp_b = otp_df[(otp_df["host"] == host) & (otp_df["weekday"] == weekday) & (otp_df["bucket"] == bucket)]
                    if len(otp_b) > 0 and otp_b["otp_try"].sum() > 0:
                        success_rate = round(100.0 * otp_b["otp_success"].sum() / otp_b["otp_try"].sum(), 2)
                        fail_rate = round(100.0 - success_rate, 2)
                        otp_thresholds = {
                            "baseline_avg": success_rate,
                            "normal_max": success_rate,
                            "monitor_threshold": round(fail_rate * 1.5, 3),
                            "critical_threshold": round(fail_rate * 2.0, 3),
                        }
                    else:
                        otp_thresholds = {"baseline_avg": None, "normal_max": None, "monitor_threshold": None, "critical_threshold": None}
                else:
                    otp_thresholds = {"baseline_avg": None, "normal_max": None, "monitor_threshold": None, "critical_threshold": None}

                hosts_result[host][weekday][bucket] = {
                    "response_time": _calc_thresholds(smps_b["response_time"]),
                    "busy_threads": _calc_thresholds(smps_b["busy_threads"]),
                    "auth_fail_rate": af_thresholds,
                    "otp_success_rate": otp_thresholds,
                }

    return hosts_result


def generate_summary(start: str, end: str, hosts_result: dict) -> str:
    """LLM으로 전체 분석 요약 1회 생성"""
    # 대표 샘플 (SSO_01, wed, 09:00 버킷)
    sample = {}
    for host in list(hosts_result.keys())[:2]:
        for wd in list(hosts_result[host].keys())[:2]:
            for bucket in ["09:00", "08:50", "10:00"]:
                if bucket in hosts_result[host][wd]:
                    sample[f"{host}/{wd}/{bucket}"] = hosts_result[host][wd][bucket]
                    break

    prompt = f"""아래는 {start}~{end} SiteMinder SSO 서비스의 호스트×요일×10분 단위 임계치 프로파일 샘플입니다.
{json.dumps(sample, ensure_ascii=False, indent=2)}

운영자를 위한 전체 분석 요약을 3~5줄로 작성하세요. JSON만 반환:
{{"analysis_summary": "요약 내용"}}"""

    resp = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content).get("analysis_summary", "")


def fetch_otp_stats(start: str, end: str) -> pd.DataFrame:
    """catalina 로그에서 OTP 성공/실패 집계"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT
            host,
            strftime('%w', datetime(timestamp, '+9 hours')) AS weekday,
            strftime('%H', datetime(timestamp, '+9 hours')) || ':' ||
            printf('%02d', CAST(strftime('%M', datetime(timestamp, '+9 hours')) AS INTEGER) / 10 * 10) AS bucket,
            log_message
        FROM log_catalina
        WHERE timestamp >= ? AND timestamp <= ?
        AND (log_message LIKE '%Request OTP Generate%'
             OR log_message LIKE '%Verification result = [true]%'
             OR log_message LIKE '%Verification result = [false]%')
    """, conn, params=(f"{start}T00:00:00.000Z", f"{end}T23:59:59.999Z"))
    conn.close()
    df["weekday"] = df["weekday"].map(WEEKDAY_MAP)
    df["otp_try"] = df["log_message"].str.contains("Request OTP Generate").astype(int)
    df["otp_success"] = df["log_message"].str.contains(r"Verification result = \[true\]", regex=True).astype(int)
    df["otp_fail"] = df["log_message"].str.contains(r"Verification result = \[false\]", regex=True).astype(int)
    return df


def main(start: str, end: str):
    print(f"임계치 프로파일 생성 시작: {start} ~ {end}")

    print("  smps_stats 로드 중...")
    smps_df = fetch_smps_stats(start, end)
    print(f"  → {len(smps_df):,}건")

    print("  swg_lib 로드 중...")
    auth_df = fetch_auth_stats(start, end)
    print(f"  → {len(auth_df):,}건")

    print("  catalina OTP 로드 중...")
    otp_df = fetch_otp_stats(start, end)
    print(f"  → {len(otp_df):,}건")

    print("  임계치 계산 중 (IQR + p50/p95)...")
    hosts_result = build_profile(smps_df, auth_df, otp_df)

    print("  LLM 분석 요약 생성 중 (1회)...")
    summary = generate_summary(start, end, hosts_result)

    profile = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_period": f"{start} ~ {end}",
        "method": "IQR outlier removal + p50/p95 percentile thresholds",
        "hosts": hosts_result,
        "analysis_summary": summary,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    total_buckets = sum(
        len(b) for h in hosts_result.values() for b in h.values()
    )
    print(f"✅ 임계치 프로파일 저장 완료: {OUTPUT_PATH}")
    print(f"   호스트: {len(hosts_result)} / 요일: {len(next(iter(hosts_result.values())))} / 총 버킷: {total_buckets}")
    print(f"   분석 요약: {summary[:100]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="임계치 프로파일 생성")
    parser.add_argument("--start", default="2026-06-22", help="기준 시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-06-28", help="기준 종료일 (YYYY-MM-DD)")
    args = parser.parse_args()
    main(args.start, args.end)