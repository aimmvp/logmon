"""
web_search_tool
- Tavily Search API를 이용한 외부 웹 검색
- generate_guide 노드에서 RAG 결과가 부족할 때 보완용
- 외부 결과는 내부 자료와 신뢰도를 구분하여 반환
"""

import os
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()

_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def _search(query: str, max_results: int) -> list[dict]:
    """Tavily API 단순 호출"""
    response = _client.search(query=query, max_results=max_results, search_depth="basic")
    return response.get("results", [])


def web_search_tool(
    query: str,
    max_results: int = 5,
    en_query: str = "",
) -> dict:
    """
    Tavily API로 외부 웹 검색.
    한국어 쿼리로 먼저 시도 → 결과 없으면 영어 쿼리로 재시도.

    Args:
        query: 검색 쿼리 (한국어 우선)
        max_results: 최대 결과 수 (기본 5)
        en_query: 영어 쿼리 (RAG 번역 결과 재사용용, 없으면 자동 생략)
    """
    translated = False
    used_query = query

    try:
        # 1차: 한국어 쿼리로 시도
        raw = _search(query, max_results)

        # 결과가 없거나 매우 적으면 영어로 재시도
        if len(raw) < 2 and en_query and en_query != query:
            print(f"  한국어 검색 결과 부족 → 영어로 재시도: {en_query}")
            raw = _search(en_query, max_results)
            used_query = en_query
            translated = True

        results = []
        for r in raw:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:500],
                "source": "web",
                "translated": translated,
            })

        return {
            "query": query,
            "used_query": used_query,
            "translated": translated,
            "results": results,
        }

    except Exception as e:
        print(f"  ⚠️ 웹 검색 실패: {e}")
        return {"query": query, "used_query": query, "translated": False, "results": []}


def format_web_results(web_output: dict) -> str:
    """
    web_search_tool 결과를 LLM 프롬프트 주입용 텍스트로 변환.
    generate_guide 노드에서 사용.
    외부 자료임을 명시하여 내부 RAG와 신뢰도 구분.
    """
    results = web_output.get("results", [])
    if not results:
        return ""

    _used = web_output.get("used_query", web_output["query"])
    _trans_note = " [영어로 검색 후 번역 적용]" if web_output.get("translated") else ""
    lines = [f"## 외부 검색 결과 (보조 자료, 쿼리: '{_used}'){_trans_note}"]
    lines.append("※ 외부 자료는 참고용이며 내부 자료보다 낮은 신뢰도로 활용하세요.")
    for i, r in enumerate(results, 1):
        lines.append(f"\n[{i}] {r['title']}")
        lines.append(f"    출처: {r['url']}")
        lines.append(f"    {r['snippet']}")

    return "\n".join(lines)


if __name__ == "__main__":
    # 동작 테스트
    test_cases = [
        ("SiteMinder Busy_Threads 높음 해결방법", "SiteMinder Busy_Threads high troubleshooting"),
        ("SiteMinder Busy_Threads가 뭐야?", "What is SiteMinder Busy_Threads?"),
    ]
    for q_ko, q_en in test_cases:
        result = web_search_tool(query=q_ko, max_results=3, en_query=q_en)
        print(f"번역 여부: {result['translated']} | 사용 쿼리: {result['used_query']}")
        for r in result["results"]:
            print(f"  [{r['title']}] {r['url']}")
            print(f"   {r['snippet'][:100]}...")