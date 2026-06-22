from typing import TypedDict, Optional
from datetime import datetime


class LogMonState(TypedDict):
    # 입력
    run_at: str                    # 실행 시각

    # load_logs
    swg_lib_logs: list[dict]
    catalina_logs: list[dict]
    smps_stats_logs: list[dict]

    # detect_anomaly
    anomaly_detected: bool
    anomaly_summary: str           # LLM이 작성한 이상 감지 요약
    anomaly_details: list[dict]    # 이상 항목 상세

    # generate_alert
    alert_message: str             # Slack 전송용 메시지
