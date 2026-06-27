"""
classify_input 노드
입력 유형 분류:
- A: 배치 트리거 (SC-001)
- B: 신규 장애 대응 요청 (SC-002 최초)
- C: 조치 결과 입력 (SC-002 반복) — incident_id 존재 + operator_feedback 포함
- D: 결과 보고서 생성 요청 (SC-003)
"""

import os
import json
from dotenv import load_dotenv
from openai import AzureOpenAI
from src.schemas.state import LogMonState

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")


def classify_input(state: LogMonState) -> LogMonState:
    """
    입력 유형을 A/B/C/D로 분류.
    - A: batch_trigger 필드가 True → 배치 트리거
    - C: incident_id 존재 + operator_input 있음 → 조치 결과 입력
    - D: incident_id 존재 + report_requested=True → 보고서 생성 요청
    - B: 그 외 자연어 입력 → 신규 장애 요청
    """

    # ── 규칙 기반 우선 분류 ────────────────────────────────────────────────────
    # A: 배치 트리거
    if state.get("batch_trigger"):
        input_type = "A"
        print(f"  [classify_input] 유형: A (배치 트리거)")
        return {**state, "input_type": input_type}

    # D: 보고서 생성 요청
    if state.get("report_requested") and state.get("incident_id"):
        input_type = "D"
        print(f"  [classify_input] 유형: D (보고서 생성 요청)")
        return {**state, "input_type": input_type, "status": "정상화완료"}

    # C: 조치 결과 입력 (incident_id + operator_input)
    if state.get("incident_id") and state.get("operator_input"):
        input_type = "C"
        print(f"  [classify_input] 유형: C (조치 결과 입력)")
        return {**state, "input_type": input_type}

    # B/기타: LLM으로 판단
    operator_input = state.get("operator_input", "")
    if not operator_input:
        # 입력 없으면 기본 A (배치)
        print(f"  [classify_input] 유형: A (기본 배치)")
        return {**state, "input_type": "A"}

    prompt = f"""다음 운영자 입력을 아래 유형 중 하나로 분류하세요.

유형:
- B: 신규 장애 대응 요청 (처음 장애 상황을 알리거나 가이드를 요청)
- C: 조치 결과 입력 (이전 조치 수행 후 결과를 보고, 추가 가이드 요청)
- D: 결과 보고서 생성 요청 (정상화 완료 후 보고서 작성 요청)

운영자 입력:
{operator_input}

JSON으로만 반환:
{{"input_type": "B" | "C" | "D", "reason": "분류 이유"}}
"""

    response = client.chat.completions.create(
        model=DEPLOYMENT,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        response_format={"type": "json_object"},
    )

    result = json.loads(response.choices[0].message.content)
    input_type = result.get("input_type", "B")
    print(f"  [classify_input] 유형: {input_type} ({result.get('reason', '')})")

    # D로 분류되면 status도 함께 변경
    updates = {"input_type": input_type}
    if input_type == "D":
        updates["status"] = "정상화완료"
        updates["normalized_at"] = state.get("normalized_at") or __import__("datetime").datetime.now().isoformat()

    return {**state, **updates}