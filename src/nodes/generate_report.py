"""
generate_report 노드 (SC-003)
- SC-002 전체 진행 이력 + 로그 기반 결과 보고서 생성
- 5개 항목: 원인 / 조치 내용 / 전후 비교 / 남은 리스크 / 재발 방지
- incident_log_tool(save_report)로 SQLite 저장 + Chroma RAG 자동 보강
"""

import os
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from src.schemas.state import LogMonState
from src.tools.incident_log_tool import incident_log_tool, get_incident_progress
from src.utils.prompt_loader import load_system_context

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")


def generate_report(state: LogMonState) -> LogMonState:
    """
    SC-003 결과 보고서 생성 노드.
    - SC-002 정상화 완료 후 자동 트리거 또는 운영자 명시 요청
    """
    incident_id = state.get("incident_id")
    if not incident_id:
        print("  [SC-003] incident_id 없음 — 스킵")
        return state

    # ── 진행 이력 조회 ─────────────────────────────────────────────────────────
    history = get_incident_progress(incident_id)
    print(f"  [SC-003] incident_id: {incident_id} | 이력: {len(history)}건")

    history_text = ""
    for h in history:
        history_text += f"\n[{h['iteration']}차]\n"
        history_text += f"- 가이드 요약: {h['summary']}\n"
        history_text += f"- 운영자 조치 결과: {h['operator_feedback'] or '(미입력)'}\n"

    # ── 프롬프트 구성 ──────────────────────────────────────────────────────────
    system_context = load_system_context()
    prompt = f"""{system_context}

---

당신은 SSO 서비스 운영 전문가입니다.
아래 장애 대응 이력을 바탕으로 결과 보고서를 작성하세요.

## 장애 정보
- 장애 ID: {incident_id}
- 감지 시각: {state.get('run_at', '')}
- 이상 감지 요약: {state.get('anomaly_summary', '')}
- 정상화 시각: {state.get('normalized_at', '(미입력)')}

## 대응 이력
{history_text}

## 로그 (정상화 전후)
- swg_lib (최근 30건):
{json.dumps(state.get('swg_lib_logs', [])[:30], ensure_ascii=False, indent=2)}
- smps_stats (최근 10건):
{json.dumps(state.get('smps_stats_logs', [])[:10], ensure_ascii=False, indent=2)}

## 보고서 작성 규칙
1. 모든 항목은 실제 로그 및 대응 이력에 근거
2. 원인은 1차/2차로 구분하여 근거 로그 명시
3. 조치 전후 비교는 수치 기반으로 작성
4. 추정 사항은 "~로 추정됨"으로 명시

## 응답 형식 (JSON만 반환)
{{
  "summary": "보고서 핵심 요약 (2~3줄)",
  "root_cause": "근본 원인 (근거 포함)",
  "actions_taken": ["1차 조치 내용", "2차 조치 내용"],
  "before_after_comparison": {{
    "항목명": {{"before": "수치", "after": "수치"}}
  }},
  "remaining_risks": ["남은 리스크 1", "남은 리스크 2"],
  "prevention_plan": ["재발 방지 방안 1", "재발 방지 방안 2"],
  "report_message": "Slack 전송용 전체 보고서 (Markdown 형식)"
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    print(f"  보고서 생성 완료: {result.get('summary', '')[:80]}")

    # ── incident_log_tool 저장 + Chroma RAG 보강 ──────────────────────────────
    incident_log_tool(
        incident_id=incident_id,
        mode="save_report",
        summary=result.get("summary", ""),
        root_cause=result.get("root_cause", ""),
        actions_taken=result.get("actions_taken", []),
        before_after_comparison=result.get("before_after_comparison", {}),
        remaining_risks=result.get("remaining_risks", []),
        prevention_plan=result.get("prevention_plan", []),
    )

    return {
        **state,
        "status": "보고서생성중",
        "guide_message": result.get("report_message", ""),
    }