"""
RAG 검증 스크립트
사용법: python -m src.scripts.verify_rag
"""

import os
from dotenv import load_dotenv
from chromadb import PersistentClient
from openai import OpenAI

load_dotenv()

# ── 설정 ────────────────────────────────────────────────────────────────────
CHROMA_PATH = "./data/chroma"
COLLECTION_NAME = "siteminder_manual"
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TOP_K = 3

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY_INGEST"))
chroma = PersistentClient(path=CHROMA_PATH)
collection = chroma.get_collection(COLLECTION_NAME)


def search(query: str, top_k: int = DEFAULT_TOP_K) -> None:
    """쿼리로 Chroma 검색 후 결과 출력"""
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
    embedding = response.data[0].embedding

    results = collection.query(query_embeddings=[embedding], n_results=top_k)

    print(f"\n{'='*60}")
    print(f"쿼리: '{query}'")
    print(f"{'='*60}")
    for i, (doc, meta, distance) in enumerate(zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        score = round(1 - distance, 4)  # cosine distance → similarity
        print(f"\n[{i+1}] 헤딩  : {meta['heading']}")
        print(f"     페이지 : {meta['page_start']}")
        print(f"     유사도 : {score}")
        print(f"     내용   : {doc[:300]}...")
    print()


def interactive() -> None:
    """대화형 검색 모드"""
    print(f"\nRAG 검증 모드 (컬렉션: {COLLECTION_NAME} / 문서 수: {collection.count()})")
    print("종료: 'q' 입력\n")

    while True:
        query = input("검색어 입력:(종료: q) ").strip()
        if query.lower() in ("q", "quit", "exit"):
            print("종료합니다.")
            break
        if not query:
            continue

        top_k_input = input(f"결과 수 (기본 {DEFAULT_TOP_K}): ").strip()
        top_k = int(top_k_input) if top_k_input.isdigit() else DEFAULT_TOP_K

        search(query, top_k)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RAG 검증 스크립트")
    parser.add_argument("--query", "-q", type=str, help="검색 쿼리 (없으면 대화형 모드)")
    parser.add_argument("--top-k", "-k", type=int, default=DEFAULT_TOP_K, help="결과 수")
    args = parser.parse_args()

    if args.query:
        search(args.query, args.top_k)
    else:
        interactive()