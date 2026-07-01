"""
generate_guide 노드 (SC-002)
- RAG 검색 (SiteMinder 매뉴얼 + 장애 이력)
- LLM 기반 장애 대응 가이드 생성
- 매 조치 명령어에 리스크 검토 포함 (TASK4 제약사항 기준)
"""

import os
import uuid
from datetime import datetime
from dotenv import load_dotenv
from openai import AzureOpenAI
from src.schemas.state import LogMonState
from src.tools.rag_search_tool import rag_search_tool, format_rag_results
from src.tools.web_search_tool import web_search_tool, format_web_results
from src.utils.prompt_loader import load_system_context

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")


def generate_guide(state: LogMonState) -> LogMonState:
    """
    SC-002 장애 대응 가이드 생성 노드.
    - 최초 호출: incident_id 신규 발급, iteration_count=1
    - 반복 호출: 기존 incident_id 유지, iteration_count+1
    """

    # ── incident_id / iteration_count 관리 ────────────────────────────────────
    incident_id = state.get("incident_id") or f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
    iteration_count = (state.get("iteration_count") or 0) + 1
    action_history = state.get("action_history") or []

    # ── RAG 검색 ──────────────────────────────────────────────────────────────
    rag_query = state.get("anomaly_summary", "")
    rag_output = rag_search_tool(query=rag_query, top_k=5)
    rag_context = format_rag_results(rag_output)

    print(f"  [SC-002] incident_id: {incident_id} | 차수: {iteration_count}")
    print(f"  RAG 검색 완료: {len(rag_output['results'])}개 문서")

    # ── 웹 검색 (RAG 결과 부족 시 보완) ──────────────────────────────────────
    web_context = ""
    avg_score = sum(r["score"] for r in rag_output["results"]) / len(rag_output["results"]) if rag_output["results"] else 0
    if avg_score < 0.45:  # RAG 유사도 평균 0.45 미만이면 웹 검색 보완
        en_query = rag_output.get("translated_query", "")
        web_output = web_search_tool(query=rag_query, max_results=3, en_query=en_query)
        web_context = format_web_results(web_output)
        if web_output["results"]:
            print(f"  웹 검색 보완: {len(web_output['results'])}건 (RAG 평균 유사도 {avg_score:.3f})")
    else:
        print(f"  웹 검색 스킵 (RAG 평균 유사도 {avg_score:.3f} ≥ 0.45)")

    # ── 이전 조치 이력 텍스트 변환 ─────────────────────────────────────────────
    history_text = ""
    if action_history:
        history_text = "\n## 이전 조치 이력\n"
        for h in action_history:
            history_text += f"\n[{h.get('iteration')}차]\n"
            history_text += f"- 제시된 가이드 요약: {h.get('guide_summary', '')}\n"
            history_text += f"- 운영자 조치 결과: {h.get('operator_feedback', '')}\n"

    # ── 프롬프트 구성 ──────────────────────────────────────────────────────────
    system_context = load_system_context()
    prompt = f"""{system_context}

---

당신은 SSO 서비스 운영 전문가입니다.
위 시스템 명세를 참고하여 아래 정보를 바탕으로 장애 대응 가이드를 생성하세요.
아래 정보를 바탕으로 장애 대응 가이드를 생성하세요.

## 장애 정보
- 장애 ID: {incident_id}
- 감지 시각: {state.get('run_at', '')}
- 이상 감지 요약: {state.get('anomaly_summary', '')}
- 이상 상세:
{_format_anomaly_details(state.get('anomaly_details', []))}

## 관련 로그
- swg_lib 로그 (최근 20건):
{state.get('swg_lib_logs', [])[:20]}
- catalina 로그 (최근 20건):
{state.get('catalina_logs', [])[:20]}
- smps_stats 로그 (최근 10건):
{state.get('smps_stats_logs', [])[:10]}

{history_text}

{rag_context}
{web_context}

## 가이드 작성 규칙
1. 판단 근거: 어떤 로그의 어떤 패턴인지 명시 (파일명/항목명 포함)
2. 추정 사항은 반드시 "~로 추정됨"으로 표현
3. 조치 명령어마다 아래 5가지를 반드시 포함:
   - 영향 범위
   - 위험도 (높음/중간/낮음)
   - 실행 전 확인 사항
   - 롤백 방법
   - 운영자 승인 필요 여부
4. 정상 판단 기준 명시
5. 참고 자료 출처 표기 (RAG 섹션명/페이지)
6. 마지막에 "▶ 위 조치 수행 후, 결과를 알려주세요." 추가

## 응답 형식 (JSON)
{{
  "guide_summary": "가이드 핵심 요약 (1~2줄)",
  "guide_message": "운영자에게 전달할 전체 가이드 (Markdown 형식)",
  "normal_criteria": "정상 판단 기준"
}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    import json
    result = json.loads(response.choices[0].message.content)

    guide_summary = result.get("guide_summary", "")
    guide_message = result.get("guide_message", "")

    print(f"  가이드 생성 완료: {guide_summary}")

    # ── action_history 누적 ────────────────────────────────────────────────────
    action_history.append({
        "iteration": iteration_count,
        "guide_summary": guide_summary,
        "operator_feedback": "",  # send_slack 이후 운영자 입력으로 채워짐
    })

    return {
        **state,
        "incident_id": incident_id,
        "iteration_count": iteration_count,
        "status": "조치중",
        "rag_results": rag_output["results"],
        "action_history": action_history,
        "guide_message": guide_message,
    }


def _format_anomaly_details(details: list[dict]) -> str:
    if not details:
        return "없음"
    lines = []
    for d in details:
        lines.append(
            f"  - [{d.get('severity', '')}] {d.get('log_type', '')} / "
            f"{d.get('host', '')}: {d.get('description', '')}"
        )
    return "\n".join(lines)