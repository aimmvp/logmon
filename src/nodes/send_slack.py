import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.schemas.state import LogMonState

load_dotenv()

client = WebClient(token=os.getenv('SLACK_BOT_TOKEN'))
CHANNEL = os.getenv('SLACK_ALERT_CHANNEL')


def send_slack(state: LogMonState) -> LogMonState:
    """Slack 알림 전송"""
    try:
        response = client.chat_postMessage(
            channel=CHANNEL,
            text=state.get('alert_message', ''),
        )
        print(f'  ✅ Slack 전송 완료: {response["ts"]}')
    except SlackApiError as e:
        print(f'  ❌ Slack 전송 실패: {e.response["error"]}')

    return state
