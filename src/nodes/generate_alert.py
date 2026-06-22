from src.schemas.state import LogMonState


def generate_alert(state: LogMonState) -> LogMonState:
    """Slack 알림 메시지 생성"""

    details_text = ''
    for d in state.get('anomaly_details', []):
        severity = d.get('severity', 'UNKNOWN')
        log_type = d.get('log_type', '')
        host = d.get('host', '')
        description = d.get('description', '')
        details_text += f'\n• [{severity}] {log_type} / {host}: {description}'

    alert_message = f"""
🚨 *SSO 이상 감지 알림*
실행 시각: {state.get('run_at', '')}

*요약*
{state.get('anomaly_summary', '')}

*상세*{details_text}
""".strip()

    print(f'  알림 메시지 생성 완료')
    return {**state, 'alert_message': alert_message}
