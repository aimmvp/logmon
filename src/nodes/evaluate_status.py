"""
evaluate_status 노드 (SC-002 반복 루프)
- 운영자 피드백 + 현재 로그를 기반으로 정상화 여부 판단
- 정상화: status → '정상화완료' → SC-003으로 연계
- 미정상화: iteration_count+1 → generate_guide 재진입
"""

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI
from src.schemas.state import LogMonState
from src.tools.incident_log_tool import incident_log_tool
from src.utils.prompt_loader import load_system_context

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
MAX_ITERATION = int(os.getenv("SC002_MAX_ITERATION", "5"))


def evaluate_status(state: LogMonState) -> LogMonState:
    """
    SC-002 조치 결과 평가 노드.
    - 운영자 피드백 + 현재 로그 기반으로 정상화 여부 판단
    - action_history 마지막 항목에 operator_feedback 업데이트
    - incident_log_tool(save_progress)로 이력 저장
    """
    incident_id = state.get("incident_id")
    iteration_count = state.get("iteration_count", 1)
    operator_input = state.get("operator_input", "")
    action_history = state.get("action_history") or []

    print(f"  [evaluate_status] incident_id: {incident_id} | 차수: {iteration_count}")

    # ── action_history 마지막 항목에 operator_feedback 업데이트 ──────────────
    if action_history:
        action_history[-1]["operator_feedback"] = operator_input

    # ── 최대 반복 횟수 초과 시 강제 종료 ──────────────────────────────────────
    if iteration_count >= MAX_ITERATION:
        print(f"  ⚠️ 최대 반복 횟수({MAX_ITERATION}) 도달 — 강제 정상화 처리")
        _save_progress(incident_id, iteration_count, "정상화완료", operator_input, action_history)
        return {
            **state,
            "status": "정상화완료",
            "normalized_at": datetime.now().isoformat(),
            "action_history": action_history,
        }

    # ── LLM으로 정상화 여부 판단 ──────────────────────────────────────────────
    system_context = load_system_context()
    prompt = f"""{system_context}

---

당신은 SSO 서비스 운영 전문가입니다.
아래 정보를 바탕으로 장애가 정상화되었는지 판단하세요.

## 장애 정보
- 장애 ID: {incident_id}
- 이상 감지 요약: {state.get('anomaly_summary', '')}
- 현재 반복 차수: {iteration_count}

## 이전 조치 이력
{_format_history(action_history)}

## 운영자 최신 피드백
{operator_input}

## 현재 로그
- swg_lib (최근 20건):
{json.dumps(state.get('swg_lib_logs', [])[:20], ensure_ascii=False)}
- smps_stats (최근 10건):
{json.dumps(state.get('smps_stats_logs', [])[:10], ensure_ascii=False)}

## 판단 기준
- 정상화: 이상 감지 요약의 문제가 해소되고 운영자가 정상화를 확인한 경우
- 미정상화: 문제가 지속되거나 새로운 이상 징후가 발생한 경우

## 응답 형식 (JSON만 반환)
{{
  "normalized": true/false,
  "reason": "판단 근거 (1~2줄)",
  "remaining_issues": "미정상화 시 남은 문제점 (정상화 시 빈 문자열)"
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    normalized = result.get("normalized", False)
    reason = result.get("reason", "")
    print(f"  정상화 여부: {normalized} | 근거: {reason}")

    if normalized:
        status = "정상화완료"
        normalized_at = datetime.now().isoformat()
    else:
        status = "조치중"
        normalized_at = state.get("normalized_at", "")

    # ── incident_log_tool save_progress ───────────────────────────────────────
    _save_progress(incident_id, iteration_count, status, operator_input, action_history)

    return {
        **state,
        "status": status,
        "normalized_at": normalized_at if normalized else state.get("normalized_at", ""),
        "action_history": action_history,
        "operator_input": "",  # 피드백 처리 완료 후 초기화
    }


def _save_progress(incident_id, iteration, status, operator_feedback, action_history):
    try:
        summary = action_history[-1].get("guide_summary", "") if action_history else ""
        guide = action_history[-1].get("guide_summary", "") if action_history else ""
        incident_log_tool(
            incident_id=incident_id,
            mode="save_progress",
            iteration=iteration,
            status=status,
            summary=summary,
            guide=guide,
            operator_feedback=operator_feedback,
        )
    except Exception as e:
        print(f"  ⚠️ 진행 이력 저장 실패: {e}")


def _format_history(action_history: list[dict]) -> str:
    if not action_history:
        return "없음"
    lines = []
    for h in action_history:
        lines.append(f"[{h.get('iteration')}차]")
        lines.append(f"  가이드 요약: {h.get('guide_summary', '')}")
        lines.append(f"  운영자 피드백: {h.get('operator_feedback', '(미입력)')}")
    return "\n".join(lines)