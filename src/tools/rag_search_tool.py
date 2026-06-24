"""
RAG 검색 Tool
- SiteMinder 매뉴얼 (Chroma: siteminder_manual)
- 장애 이력 (Chroma: incident_history) — SC-003 보고서 저장 후 자동 보강
"""

import os
from enum import Enum
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI, AzureOpenAI
from chromadb import PersistentClient

load_dotenv()

# ── 설정 ─────────────────────────────────────────────────────────────────────
CHROMA_PATH = "./data/chroma"
COLLECTION_MANUAL = "siteminder_manual"
COLLECTION_INCIDENT = "incident_history"
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TOP_K = 5

_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_INGEST"))
_chroma_client = PersistentClient(path=CHROMA_PATH)

# Azure OpenAI — 쿼리 영어 변환용 LLM
_azure_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)
AZURE_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")


class SourceFilter(str, Enum):
    MANUAL = "manual"
    INCIDENT_HISTORY = "incident_history"
    ALL = "all"


def _translate_to_english(query: str) -> str:
    """
    한국어/혼합 쿼리를 영어로 변환.
    영어 전용 매뉴얼 검색 정확도 향상 목적.
    이미 영어면 그대로 반환.
    """
    response = _azure_client.chat.completions.create(
        model=AZURE_DEPLOYMENT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a technical translator specialized in SSO and SiteMinder systems. "
                    "Translate the given query into English for searching a SiteMinder technical manual. "
                    "If the query is already in English, return it as-is. "
                    "Return ONLY the translated query, no explanation."
                ),
            },
            {"role": "user", "content": query},
        ],
        max_tokens=100,
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def _get_embedding(text: str) -> list[float]:
    response = _openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[text],
    )
    return response.data[0].embedding


def _search_collection(
    collection_name: str,
    embedding: list[float],
    top_k: int,
) -> list[dict]:
    """단일 컬렉션 검색. 컬렉션 없으면 빈 리스트 반환."""
    try:
        collection = _chroma_client.get_collection(collection_name)
    except Exception:
        return []

    results = collection.query(query_embeddings=[embedding], n_results=top_k)
    output = []
    for doc, meta, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "source": collection_name,
            "heading": meta.get("heading", ""),
            "page_start": meta.get("page_start", ""),
            "content": doc,
            "score": round(1 - distance, 4),  # cosine distance → similarity
        })
    return output


def rag_search_tool(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    source_filter: SourceFilter = SourceFilter.ALL,
) -> dict:
    """
    SiteMinder 매뉴얼 및 장애 이력 RAG 검색.

    Args:
        query: 검색 쿼리 (한국어/영어 모두 가능)
        top_k: 반환할 결과 수 (기본 5)
        source_filter: 검색 대상 (manual / incident_history / all)

    Returns:
        {
            "query": str,
            "source_filter": str,
            "results": [
                {
                    "source": "siteminder_manual" | "incident_history",
                    "heading": str,
                    "page_start": int,
                    "content": str,
                    "score": float   # 0~1, 높을수록 관련도 높음
                }
            ]
        }
    """
    # 한국어/혼합 쿼리 → 영어 변환 후 임베딩 (영어 매뉴얼 검색 정확도 향상)
    translated_query = _translate_to_english(query)
    if translated_query != query:
        print(f"  쿼리 번역: '{query}' → '{translated_query}'")
    embedding = _get_embedding(translated_query)
    results = []

    if source_filter in (SourceFilter.MANUAL, SourceFilter.ALL):
        results += _search_collection(COLLECTION_MANUAL, embedding, top_k)

    if source_filter in (SourceFilter.INCIDENT_HISTORY, SourceFilter.ALL):
        results += _search_collection(COLLECTION_INCIDENT, embedding, top_k)

    # ALL 모드: score 기준 정렬 후 top_k개만 반환
    if source_filter == SourceFilter.ALL:
        results = sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]

    return {
        "query": query,
        "translated_query": translated_query,
        "source_filter": source_filter.value,
        "results": results,
    }


def format_rag_results(rag_output: dict) -> str:
    """
    rag_search_tool 결과를 LLM 프롬프트 주입용 텍스트로 변환.
    generate_guide 노드에서 사용.
    """
    results = rag_output.get("results", [])
    if not results:
        return "관련 문서를 찾지 못했습니다."

    translated = rag_output.get("translated_query", "")
    query_label = f"{rag_output['query']}"
    if translated and translated != rag_output["query"]:
        query_label += f" → {translated}"
    lines = [f"## RAG 검색 결과 (쿼리: '{query_label}')"]
    for i, r in enumerate(results, 1):
        source_label = "매뉴얼" if r["source"] == COLLECTION_MANUAL else "장애이력"
        lines.append(
            f"\n[{i}] 출처: {source_label} | 섹션: {r['heading']} | 페이지: {r['page_start']} | 유사도: {r['score']}"
        )
        lines.append(r["content"][:500])

    return "\n".join(lines)


if __name__ == "__main__":
    # 간단 동작 테스트
    queries = [
        "Session pool exhausted CPU 부하",
        "인증 실패 AuthReason",
        "Busy_Threads 임계값",
    ]
    for q in queries:
        result = rag_search_tool(query=q, top_k=3)
        print(f"\n쿼리: {q}")
        for r in result["results"]:
            print(f"  [{r['score']}] {r['heading']} (p.{r['page_start']})")
            print(f"   {r['content'][:150]}...")