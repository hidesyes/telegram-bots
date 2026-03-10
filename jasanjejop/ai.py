import json
import os
from openai import OpenAI
from config import OPENAI_API_KEY, STYLE_PROFILE_PATH, TAVILY_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# 대화 히스토리 (user_id → 메시지 목록)
conversation_histories = {}
MAX_HISTORY = 10


def get_history(user_id: int) -> list:
    return conversation_histories.get(user_id, [])


def add_to_history(user_id: int, role: str, content: str):
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []
    conversation_histories[user_id].append({"role": role, "content": content})
    # 최근 MAX_HISTORY 쌍만 유지
    if len(conversation_histories[user_id]) > MAX_HISTORY * 2:
        conversation_histories[user_id] = conversation_histories[user_id][-MAX_HISTORY * 2:]


def clear_history(user_id: int):
    conversation_histories[user_id] = []


def search_web(query: str) -> str:
    """Tavily로 실시간 투자 관련 웹 검색"""
    if not TAVILY_API_KEY:
        return ""
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        results = tavily.search(
            query=query,
            max_results=4,
            search_depth="advanced",
            include_domains=["naver.com", "reuters.com", "bloomberg.com", "hankyung.com", "mk.co.kr", "sedaily.com"]
        )
        texts = []
        for r in results.get("results", []):
            texts.append(f"[{r['title']}]\n{r['content'][:500]}")
        return "\n\n".join(texts)
    except Exception:
        return ""


def load_style_profile() -> dict:
    try:
        with open(STYLE_PROFILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_style_profile(profile: dict):
    with open(STYLE_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def analyze_and_update_style(article_content: str):
    """새 글에서 스타일 분석 후 기존 프로필에 반영"""
    existing = load_style_profile()
    existing_text = json.dumps(existing, ensure_ascii=False) if existing else "없음"

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 투자 콘텐츠 분석 전문가입니다.\n"
                    "새로운 글과 기존 스타일 프로필을 합쳐서 더 정확한 프로필을 만들어주세요.\n\n"
                    "반드시 아래 JSON 형식으로만 반환하세요:\n"
                    "{\n"
                    '  "writing_style": "말투/문체 특징",\n'
                    '  "personality": "성격 특징",\n'
                    '  "key_principles": ["핵심 투자 원칙 1", "원칙 2"],\n'
                    '  "recurring_phrases": ["자주 쓰는 표현 1", "표현 2"],\n'
                    '  "tone": "전체적인 톤",\n'
                    '  "topics": ["주로 다루는 주제 1", "주제 2"]\n'
                    "}"
                )
            },
            {
                "role": "user",
                "content": (
                    f"기존 스타일 프로필:\n{existing_text}\n\n"
                    f"새로운 글:\n{article_content[:3000]}"
                )
            }
        ],
        response_format={"type": "json_object"}
    )

    updated = json.loads(response.choices[0].message.content)
    save_style_profile(updated)
    return updated


def ask_as_jasanjejop(question: str, related_articles: list, user_id: int = 0) -> str:
    """자산제곱 스타일로 답변 생성 (대화 맥락 + 실시간 검색 포함)"""
    profile = load_style_profile()

    if not profile:
        return "아직 자산제곱님의 글이 충분히 분석되지 않았어요. 링크를 보내서 글을 먼저 추가해주세요."

    profile_text = json.dumps(profile, ensure_ascii=False, indent=2)

    # 저장된 글 컨텍스트 (날짜 포함)
    context_parts = []
    for article in related_articles:
        title = article["metadata"].get("title", "")
        content = article["content"][:1200]
        written_date_str = article["metadata"].get("written_date", "")
        try:
            from datetime import datetime as _dt
            written_date = _dt.fromisoformat(written_date_str)
            date_label = f"{written_date.month}월 {written_date.day}일"
        except (ValueError, AttributeError):
            date_label = written_date_str[:10] if written_date_str else "날짜 미상"
        context_parts.append(f"[{date_label}자 글: {title}]\n{content}")
    stored_context = "\n\n---\n\n".join(context_parts) if context_parts else "관련 글 없음"

    # 실시간 웹 검색
    web_context = search_web(f"투자 {question} 시장 분석 2024 2025")
    if web_context:
        web_section = f"\n\n[실시간 검색 정보]\n{web_context}"
    else:
        web_section = ""

    system_prompt = (
        "당신은 투자자 '자산제곱'입니다.\n"
        "아래는 자산제곱님의 글쓰기 스타일과 투자 철학 분석입니다:\n\n"
        f"{profile_text}\n\n"
        "답변 규칙:\n"
        "1. 질문 유형에 맞게 자유롭게 답하라. 형식을 강요하지 말 것.\n"
        "2. 저장된 글에서 관련 내용을 찾았으면, 반드시 'N월 N일자 글에서...'로 날짜를 밝히고 실제 내용을 인용하라.\n"
        "3. 저장된 글 내용과 GPT 자체 지식 / 실시간 검색 결과를 명확히 구분하라.\n"
        "4. 저장된 글과 무관한 일반 질문은 GPT처럼 자연스럽게 답하라.\n"
        "5. 스타일 프로필이 있으면 자산제곱님의 말투로, 없으면 그냥 자연스럽게 답하라."
    )

    # 대화 히스토리 가져오기
    history = get_history(user_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": (
            f"[자산제곱님 글 참고]\n{stored_context}"
            f"{web_section}\n\n"
            f"질문: {question}"
        )
    })

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=messages,
        max_tokens=1500
    )

    answer = response.choices[0].message.content

    # 히스토리 업데이트
    add_to_history(user_id, "user", question)
    add_to_history(user_id, "assistant", answer)

    return answer
