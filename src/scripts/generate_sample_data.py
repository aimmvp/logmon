"""
smps_stats 샘플 데이터 생성 스크립트
- 지난주(6/14~6/20) 정상 데이터 생성
- 이번주 이상 데이터 생성 (시나리오 1: busy_threads 급증 / 시나리오 2: response_time 급증)

실행:
    python -m src.scripts.generate_sample_data --mode baseline   # 지난주 정상 데이터
    python -m src.scripts.generate_sample_data --mode scenario1  # busy_threads 급증
    python -m src.scripts.generate_sample_data --mode scenario2  # response_time 급증
    python -m src.scripts.generate_sample_data --mode all        # 전체
"""

import argparse
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("SQLITE_DB_PATH")
HOSTS = ["SSO_01", "SSO_02", "SSO_03", "SSO_04"]

# ── 정상 범위 파라미터 (시간대별) ────────────────────────────────────────────
def normal_params(hour: int) -> dict:
    """시간대별 정상 파라미터 반환"""
    # busy_threads: 새벽 높고 낮에 낮음 (실측 패턴 반영)
    bt_map = {
        0: 20, 1: 27, 2: 25, 3: 11, 4: 21, 5: 23,
        6: 23, 7: 22, 8: 21, 9: 10, 10: 5, 11: 1,
        12: 0, 13: 0, 14: 0, 15: 0, 16: 0, 17: 0,
        18: 0, 19: 0, 20: 0, 21: 0, 22: 1, 23: 4,
    }
    tp_map = {
        0: 310, 1: 308, 2: 309, 3: 309, 4: 311, 5: 312,
        6: 313, 7: 314, 8: 314, 9: 315, 10: 315, 11: 315,
        12: 314, 13: 314, 14: 313, 15: 313, 16: 313, 17: 312,
        18: 312, 19: 312, 20: 311, 21: 311, 22: 311, 23: 307,
    }
    return {
        "response_time": 17.5,
        "busy_threads": bt_map.get(hour, 5),
        "throughput": tp_map.get(hour, 310),
        "wait_time_in_queue": 0.005,
        "exceeded_limit": 0,
        "core_result": "N",
        "current_connections": 38,
        "max_connections": 435,
        "current_threads": 8,
        "max_threads": 8,
    }


def jitter(value: float, pct: float = 0.03) -> float:
    """±pct% 범위 노이즈 추가"""
    return round(value * (1 + random.uniform(-pct, pct)), 3)


def make_row(host: str, ts: datetime, params: dict, email_id: int = 9999) -> tuple:
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return (
        email_id,
        "normal",
        ts_str,
        host,
        "smps_stats",
        int(random.uniform(800000, 1200000)),   # msgs
        jitter(params["throughput"]),
        jitter(params["response_time"]),
        jitter(params["wait_time_in_queue"]),
        random.randint(4, 8),                   # max_hp_msg
        random.randint(4, 8),                   # max_np_msg
        0,                                      # current_depth
        random.randint(5, 10),                  # max_depth
        params["current_threads"],
        params["max_threads"],
        max(0, int(jitter(params["busy_threads"], 0.1))),
        params["current_connections"],
        params["max_connections"],
        params["exceeded_limit"],
        params["core_result"],
        datetime.now().isoformat(),
    )


def insert_rows(rows: list[tuple]) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("""
        INSERT INTO log_smps_stats
        (email_id, status, timestamp, host, service,
         msgs, throughput, response_time, wait_time_in_queue,
         max_hp_msg, max_np_msg, current_depth, max_depth,
         current_threads, max_threads, busy_threads,
         current_connections, max_connections,
         exceeded_limit, core_result, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    count = cur.rowcount
    conn.close()
    return count


# ── 지난주 정상 데이터 생성 (6/14 00:00 ~ 6/20 23:59) ────────────────────────
def generate_baseline():
    """지난주 전체 1분 단위 정상 데이터"""
    print("지난주 정상 데이터 생성 중...")
    start = datetime(2026, 6, 14, 0, 0, 0, tzinfo=timezone.utc)
    end   = datetime(2026, 6, 20, 23, 59, 0, tzinfo=timezone.utc)

    rows = []
    ts = start
    while ts <= end:
        hour = ts.hour
        params = normal_params(hour)
        for host in HOSTS:
            rows.append(make_row(host, ts, params))
        ts += timedelta(minutes=1)

        if len(rows) >= 5000:
            insert_rows(rows)
            print(f"  저장: {ts.strftime('%Y-%m-%d %H:%M')}")
            rows = []

    if rows:
        insert_rows(rows)

    print(f"✅ 지난주 정상 데이터 생성 완료")


# ── 시나리오 1: busy_threads 급증 (이번주 6/23 09:00~09:30) ──────────────────
def generate_scenario1():
    """
    SC1: 출근 시간대 busy_threads 급증
    - 6/23(월) 09:00~09:29: 정상 → 이상 점진적 증가 (10 → 50)
    - 비교 기준: 지난주 6/16(월) 09:00~09:29 정상 데이터
    """
    print("시나리오1 (busy_threads 급증) 데이터 생성 중...")
    rows = []

    # 이번주 이상 데이터 (6/23 09:00~09:29)
    for minute in range(30):
        ts = datetime(2026, 6, 28, 0, minute, 0, tzinfo=timezone.utc)  # 09:00 KST = 00:00 UTC
        hour = ts.hour
        params = normal_params(hour).copy()

        # 점진적 급증: 10 → 50
        progress = minute / 29
        params["busy_threads"] = int(10 + progress * 40)
        if params["busy_threads"] >= 40:
            params["exceeded_limit"] = 1
            params["core_result"] = "Y"

        for host in HOSTS:
            rows.append(make_row(host, ts, params, email_id=9001))

    # 지난주 정상 데이터 (6/16 09:00~09:29) — 비교 기준
    for minute in range(30):
        ts = datetime(2026, 6, 16, 0, minute, 0, tzinfo=timezone.utc)  # 09:00 KST = 00:00 UTC
        params = normal_params(9).copy()
        for host in HOSTS:
            rows.append(make_row(host, ts, params, email_id=9001))

    count = insert_rows(rows)
    print(f"✅ 시나리오1 데이터 생성 완료 ({count}건)")
    print("   이번주 6/23 09:00~09:29 busy_threads 10→50 급증")
    print("   지난주 6/16 09:00~09:29 정상 데이터 포함")


# ── 시나리오 2: response_time 급증 (이번주 6/24 13:00~13:30) ─────────────────
def generate_scenario2():
    """
    SC2: 점심 직후 response_time 급증
    - 6/24(화) 13:00~13:29: 정상 → 이상 점진적 증가 (17.5 → 40ms)
    - 비교 기준: 지난주 6/17(화) 13:00~13:29 정상 데이터
    """
    print("시나리오2 (response_time 급증) 데이터 생성 중...")
    rows = []

    # 이번주 이상 데이터 (6/24 13:00~13:29)
    for minute in range(30):
        ts = datetime(2026, 6, 28, 4, minute, 0, tzinfo=timezone.utc)  # 13:00 KST = 04:00 UTC
        params = normal_params(13).copy()

        # 점진적 급증: 17.5 → 40ms
        progress = minute / 29
        params["response_time"] = round(17.5 + progress * 22.5, 3)
        if params["response_time"] >= 20.0:
            params["exceeded_limit"] = 1

        for host in HOSTS:
            rows.append(make_row(host, ts, params, email_id=9002))

    # 지난주 정상 데이터 (6/17 13:00~13:29) — 비교 기준
    for minute in range(30):
        ts = datetime(2026, 6, 17, 4, minute, 0, tzinfo=timezone.utc)  # 13:00 KST = 04:00 UTC
        params = normal_params(13).copy()
        for host in HOSTS:
            rows.append(make_row(host, ts, params, email_id=9002))

    count = insert_rows(rows)
    print(f"✅ 시나리오2 데이터 생성 완료 ({count}건)")
    print("   이번주 6/24 13:00~13:29 response_time 17.5→40ms 급증")
    print("   지난주 6/17 13:00~13:29 정상 데이터 포함")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="smps_stats 샘플 데이터 생성")
    parser.add_argument(
        "--mode",
        choices=["baseline", "scenario1", "scenario2", "all"],
        default="all",
        help="생성할 데이터 유형",
    )
    args = parser.parse_args()

    if args.mode in ("baseline", "all"):
        generate_baseline()
    if args.mode in ("scenario1", "all"):
        generate_scenario1()
    if args.mode in ("scenario2", "all"):
        generate_scenario2()