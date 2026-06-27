from typing import TypedDict, Optional


class LogMonState(TypedDict):
    # ── 공통 ──────────────────────────────────────────────────────────────────
    run_at: str                        # 실행 시각
    input_type: Optional[str]          # A/B/C/D 분류 결과
    batch_trigger: Optional[bool]      # True = 배치 트리거 (SC-001)
    operator_input: Optional[str]      # 운영자 자연어 입력 (SC-002/003)
    report_requested: Optional[bool]   # True = 보고서 생성 요청 (SC-003)

    # ── load_logs ─────────────────────────────────────────────────────────────
    swg_lib_logs: list[dict]
    catalina_logs: list[dict]
    smps_stats_logs: list[dict]

    # ── detect_anomaly (SC-001) ───────────────────────────────────────────────
    anomaly_detected: bool
    anomaly_summary: str               # LLM이 작성한 이상 감지 요약
    anomaly_details: list[dict]        # 이상 항목 상세

    # ── generate_alert (SC-001) ───────────────────────────────────────────────
    alert_message: str                 # Slack 전송용 메시지

    # ── SC-002 장애 대응 가이드 ───────────────────────────────────────────────
    incident_id: Optional[str]         # 장애 식별자 (SC-002 세션 유지용)
    iteration_count: int               # SC-002 반복 차수
    status: str                        # 정상 / 모니터링 / 조치중 / 정상화완료 / 보고서생성중
    action_history: list[dict]         # 매 턴 가이드 + 운영자 피드백 누적
    rag_results: list[dict]            # RAG 검색 결과 (원본)
    guide_message: str                 # 생성된 장애 대응 가이드 (Slack 전송용)
    normalized_at: Optional[str]       # 정상화 확인 시각 (SC-003 트리거 시점)