from src.schemas.state import LogMonState


def send_slack(state: LogMonState) -> LogMonState:
    """Slack 알림 전송 (stub)"""
    print('  [STUB] Slack 전송 예정:')
    print(state.get('alert_message', ''))
    return state
