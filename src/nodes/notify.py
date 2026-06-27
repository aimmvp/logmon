"""
notify 노드 (send_slack 대체)
- level에 따라 Slack 메시지 색상/포맷 분기
- monitor: 노란색 (모니터링 필요)
- urgent : 빨간색 (즉시 조치 필요)
- guide  : 파란색 (장애 대응 가이드)
- report : 초록색 (결과 보고서)
"""

import os
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.schemas.state import LogMonState

load_dotenv()

_client = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
CHANNEL = os.getenv("SLACK_ALERT_CHANNEL")

# level별 색상
LEVEL_COLOR = {
    "monitor": "#F59E0B",  # 노란색
    "urgent":  "#EF4444",  # 빨간색
    "guide":   "#3B82F6",  # 파란색
    "report":  "#10B981",  # 초록색
}

LEVEL_EMOJI = {
    "monitor": "🟡",
    "urgent":  "🔴",
    "guide":   "🔵",
    "report":  "🟢",
}

LEVEL_TITLE = {
    "monitor": "모니터링 필요",
    "urgent":  "즉시 조치 필요",
    "guide":   "장애 대응 가이드",
    "report":  "장애 대응 결과 보고서",
}


def _detect_level(state: LogMonState) -> str:
    """state 기반으로 알림 level 자동 판단"""
    status = state.get("status", "정상")
    alert_msg = state.get("alert_message", "")

    if status == "보고서생성중":
        return "report"
    if status == "조치중" or state.get("guide_message"):
        if "즉시 조치 필요" in alert_msg:
            return "urgent"
        return "guide"
    if state.get("anomaly_detected"):
        if "즉시 조치 필요" in alert_msg:
            return "urgent"
        return "monitor"
    return "monitor"


def _build_attachment(level: str, title: str, message: str, incident_id: str = None) -> dict:
    """Slack attachment 포맷 생성"""
    emoji = LEVEL_EMOJI.get(level, "⚪")
    color = LEVEL_COLOR.get(level, "#6B7280")
    level_title = LEVEL_TITLE.get(level, "알림")

    header = f"{emoji} *{level_title}*"
    if incident_id:
        header += f"  |  `{incident_id}`"

    return {
        "color": color,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": header},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message[:2900]},  # Slack 3000자 제한 여유
            },
        ],
    }


def notify(state: LogMonState) -> LogMonState:
    """level 기반 Slack 알림 전송"""
    level = _detect_level(state)

    # 전송할 메시지 선택
    if level == "report":
        message = state.get("guide_message", "")
        title = LEVEL_TITLE["report"]
    elif level in ("guide", "urgent") and state.get("guide_message"):
        message = state.get("guide_message", "")
        title = LEVEL_TITLE["guide"]
    else:
        message = state.get("alert_message", "")
        title = LEVEL_TITLE.get(level, "알림")

    if not message:
        print(f"  ⚠️ 전송할 메시지 없음 (level: {level})")
        return state

    incident_id = state.get("incident_id")

    try:
        attachment = _build_attachment(level, title, message, incident_id)
        response = _client.chat_postMessage(
            channel=CHANNEL,
            text=f"{LEVEL_EMOJI.get(level, '')} {title}",  # 알림 미리보기용
            attachments=[attachment],
        )
        print(f"  ✅ Slack 전송 완료 (level: {level}): {response['ts']}")
    except SlackApiError as e:
        print(f"  ❌ Slack 전송 실패: {e.response['error']}")

    return state


# 하위 호환성 유지 (기존 send_slack 참조 대비)
send_slack = notify