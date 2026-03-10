import hashlib
import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime, timedelta
from config import DB_PATH, OPENAI_API_KEY

# ChromaDB 초기화
client = chromadb.PersistentClient(path=DB_PATH)
openai_ef = embedding_functions.OpenAIEmbeddingFunction(
    api_key=OPENAI_API_KEY,
    model_name="text-embedding-3-small"
)

collection = client.get_or_create_collection(
    name="jasanjejop_articles",
    embedding_function=openai_ef
)


def find_similar_articles(content: str, threshold: float = 0.15, exclude_url: str = None) -> list:
    """유사 글 검색 (거리 기준, 낮을수록 유사)"""
    total = collection.count()
    if total == 0:
        return []

    results = collection.query(
        query_texts=[content],
        n_results=min(10, total),
        include=["metadatas", "distances"]
    )

    if not results["ids"][0]:
        return []

    similar = []
    for i, doc_id in enumerate(results["ids"][0]):
        distance = results["distances"][0][i]
        metadata = results["metadatas"][0][i]

        # 임계값 이하(유사)이고 자기 자신(같은 URL) 제외
        if distance < threshold and metadata.get("url") != exclude_url:
            similar.append({
                "id": doc_id,
                "distance": distance,
                "metadata": metadata
            })

    return similar


def deduplicate_all() -> int:
    """전체 글 중 유사 글 탐지 후 오래된 글 삭제 (일회성 정리)"""
    all_docs = collection.get()
    if not all_docs["ids"]:
        return 0

    deleted_ids = set()
    total = len(all_docs["ids"])

    for i in range(total):
        doc_id = all_docs["ids"][i]
        if doc_id in deleted_ids:
            continue

        metadata = all_docs["metadatas"][i]
        doc_text = all_docs["documents"][i]
        url = metadata.get("url", "")
        written_date_str = metadata.get("written_date", "")

        similar_list = find_similar_articles(doc_text, threshold=0.15, exclude_url=url)

        for similar in similar_list:
            similar_id = similar["id"]
            if similar_id in deleted_ids:
                continue

            similar_date_str = similar["metadata"].get("written_date", "")

            # 날짜 비교: 더 오래된 글 삭제
            try:
                current_date = datetime.fromisoformat(written_date_str)
                similar_date = datetime.fromisoformat(similar_date_str)

                if current_date >= similar_date:
                    # 현재 글이 최신 → 유사 글(older) 삭제
                    collection.delete(ids=[similar_id])
                    deleted_ids.add(similar_id)
                else:
                    # 유사 글이 최신 → 현재 글 삭제 후 루프 종료
                    collection.delete(ids=[doc_id])
                    deleted_ids.add(doc_id)
                    break
            except ValueError:
                continue

    return len(deleted_ids)


ARTICLE_CUTOFF = datetime(2025, 11, 1)


def delete_articles_before(cutoff_str: str) -> int:
    """특정 날짜 이전 글 전부 삭제"""
    cutoff = datetime.fromisoformat(cutoff_str)

    all_docs = collection.get()
    if not all_docs["ids"]:
        return 0

    ids_to_delete = []
    for i, metadata in enumerate(all_docs["metadatas"]):
        written_date_str = metadata.get("written_date", "")
        try:
            written_date = datetime.fromisoformat(written_date_str)
            if written_date < cutoff:
                ids_to_delete.append(all_docs["ids"][i])
        except ValueError:
            continue

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)

    return len(ids_to_delete)


def add_article(article: dict) -> str:
    """글 추가 (이미 있으면 덮어씀, 유사 글 있으면 날짜 비교 후 처리)"""
    # 2025-11-01 이전 글 저장 거부
    try:
        written_date = datetime.fromisoformat(article.get("written_date", ""))
        if written_date < ARTICLE_CUTOFF:
            return "too_old"
    except ValueError:
        pass

    doc_id = hashlib.md5(article["url"].encode()).hexdigest()

    # 한국어 기준 토큰 한계(8192) 초과 방지 — 약 2500자로 제한
    doc_text = f"{article['title']}\n\n{article['content']}"[:2500]

    # 유사 글 검색
    similar_list = find_similar_articles(doc_text, threshold=0.15, exclude_url=article["url"])

    for similar in similar_list:
        similar_date_str = similar["metadata"].get("written_date", "")
        new_date_str = article.get("written_date", "")

        try:
            similar_date = datetime.fromisoformat(similar_date_str)
            new_date = datetime.fromisoformat(new_date_str)

            if new_date >= similar_date:
                # 새 글이 더 최신 → 기존 유사 글 삭제 후 새 글 저장
                collection.delete(ids=[similar["id"]])
            else:
                # 기존 글이 더 최신 → 새 글 저장 스킵
                return "skipped"
        except ValueError:
            continue

    collection.upsert(
        ids=[doc_id],
        documents=[doc_text],
        metadatas=[{
            "url": article["url"],
            "title": article["title"],
            "written_date": article["written_date"],
            "scraped_date": article["scraped_date"]
        }]
    )
    return doc_id


def search_articles(query: str, n_results: int = 3) -> list:
    """질문과 관련된 글 검색"""
    total = collection.count()
    if total == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, total)
    )

    if not results["documents"][0]:
        return []

    articles = []
    for i, doc in enumerate(results["documents"][0]):
        articles.append({
            "content": doc,
            "metadata": results["metadatas"][0][i]
        })
    return articles


def delete_old_articles() -> int:
    """작성일 기준 6개월 이상 지난 글 삭제"""
    cutoff = datetime.now() - timedelta(days=180)

    all_docs = collection.get()
    if not all_docs["ids"]:
        return 0

    ids_to_delete = []
    for i, metadata in enumerate(all_docs["metadatas"]):
        written_date_str = metadata.get("written_date", "")
        try:
            written_date = datetime.fromisoformat(written_date_str)
            if written_date < cutoff:
                ids_to_delete.append(all_docs["ids"][i])
        except ValueError:
            continue

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)

    return len(ids_to_delete)


def get_all_articles() -> list:
    """전체 글 목록 반환"""
    all_docs = collection.get()
    if not all_docs["ids"]:
        return []

    articles = []
    for i, doc_id in enumerate(all_docs["ids"]):
        articles.append({
            "id": doc_id,
            "metadata": all_docs["metadatas"][i]
        })
    # 작성일 최신순 정렬
    articles.sort(key=lambda x: x["metadata"].get("written_date", ""), reverse=True)
    return articles


def clear_all_articles() -> int:
    """저장된 글 전부 삭제"""
    all_docs = collection.get()
    if not all_docs["ids"]:
        return 0
    collection.delete(ids=all_docs["ids"])
    return len(all_docs["ids"])


def get_count() -> int:
    return collection.count()
