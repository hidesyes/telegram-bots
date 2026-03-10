import json
import os
from datetime import datetime
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
        model="gpt-4o-mini",
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

    try:
        updated = json.loads(response.choices[0].message.content)
        if updated:  # 빈 객체로 덮어씌우지 않도록 검증
            save_style_profile(updated)
        return updated
    except (json.JSONDecodeError, Exception):
        return existing  # 파싱 실패 시 기존 프로필 유지


def rewrite_query_for_search(question: str) -> str:
    """사용자 질문을 ChromaDB 검색에 최적화된 쿼리로 변환"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "사용자 질문을 투자 문서 검색에 최적화된 핵심 키워드 문장으로 변환하라. "
                        "30자 이내로. 설명 없이 변환된 쿼리만 반환."
                    )
                },
                {"role": "user", "content": question}
            ],
            max_tokens=50
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return question  # 실패 시 원본 쿼리 사용


def extract_top_stocks(briefing_text: str, articles: list) -> str:
    """브리핑 내용에서 자주 언급되고 맥락상 적합한 종목 Top 3 추출"""
    # 원문 글 내용도 함께 전달해서 언급 빈도 + 맥락 분석
    articles_text = "\n\n".join(
        f"[{a['metadata'].get('written_date','')[:10]}] {a['metadata'].get('title','')}"
        for a in articles
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "투자 브리핑과 원문 글 목록을 분석하여 "
                        "여러 번 언급되고 현재 브리핑 맥락과 가장 적합한 종목 3가지를 추출하라.\n\n"
                        "반드시 아래 JSON 형식으로만 반환:\n"
                        '{"stocks": ['
                        '{"name": "종목명", "ticker": "티커(없으면 빈 문자열)", '
                        '"reason": "선정 이유 1줄", "mentions": 언급횟수(숫자)}'
                        "]}"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"[브리핑 내용]\n{briefing_text}\n\n"
                        f"[원문 글 목록]\n{articles_text}"
                    )
                }
            ],
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        stocks = data.get("stocks", [])[:3]
        if not stocks:
            return ""

        lines = ["📌 주목 종목 Top 3\n"]
        medals = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(stocks):
            ticker = f" ({s['ticker']})" if s.get("ticker") else ""
            lines.append(
                f"{medals[i]} {s['name']}{ticker}\n"
                f"   언급 {s.get('mentions', '-')}회 · {s['reason']}"
            )
        return "\n".join(lines)
    except Exception:
        return ""


def generate_digest(articles: list) -> str:
    """최근 수집된 글들을 자산제곱 스타일로 브리핑 생성"""
    profile = load_style_profile()
    profile_text = json.dumps(profile, ensure_ascii=False, indent=2) if profile else ""

    articles_text = ""
    for a in articles:
        title = a["metadata"].get("title", "")
        date = a["metadata"].get("written_date", "")[:10]
        articles_text += f"[{date}] {title}\n"

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"당신은 자산제곱님의 분신입니다.\n{profile_text}\n\n"
                        "최근 수집된 글 목록을 바탕으로 오늘의 투자 브리핑을 자산제곱 스타일로 작성하세요. "
                        "300~500자로. 결론을 먼저 제시하고 근거를 설명하는 구조로. 한국어로."
                    )
                },
                {"role": "user", "content": f"최근 글 목록:\n{articles_text}"}
            ],
            max_tokens=600
        )
        return "📰 오늘의 자산제곱 브리핑\n\n" + response.choices[0].message.content
    except Exception as e:
        return f"브리핑 생성 중 오류가 발생했어요. ({type(e).__name__})"


def ask_as_jasanjejop(question: str, related_articles: list, user_id: int = 0) -> str:
    """자산제곱 스타일로 답변 생성 (대화 맥락 + 실시간 검색 포함)"""
    profile = load_style_profile()

    if not profile:
        return "아직 자산제곱님의 글이 충분히 분석되지 않았어요. 링크를 보내서 글을 먼저 추가해주세요."

    profile_text = json.dumps(profile, ensure_ascii=False, indent=2)

    # 저장된 글 컨텍스트 (날짜 + 유사도 포함)
    context_parts = []
    for article in related_articles:
        title = article["metadata"].get("title", "")
        content = article["content"][:1200]
        written_date_str = article["metadata"].get("written_date", "")
        similarity = article.get("similarity", None)
        try:
            written_date = datetime.fromisoformat(written_date_str)
            date_label = f"{written_date.month}월 {written_date.day}일"
            # 3개월 이상 오래된 글은 표시
            age_days = (datetime.now() - written_date).days
            age_note = " ⚠️3개월+ 오래된 글" if age_days > 90 else ""
        except (ValueError, AttributeError):
            date_label = written_date_str[:10] if written_date_str else "날짜 미상"
            age_note = ""
        # 유사도 레이블
        if similarity is not None:
            if similarity > 0.75:
                sim_label = "매우 관련 높음"
            elif similarity > 0.50:
                sim_label = "관련 있음"
            elif similarity > 0.30:
                sim_label = "약하게 관련"
            else:
                sim_label = "참고용"
            header = f"[{date_label}자 글{age_note}: {title}] (관련도: {sim_label}, {int(similarity*100)}%)"
        else:
            header = f"[{date_label}자 글{age_note}: {title}]"
        context_parts.append(f"{header}\n{content}")
    stored_context = "\n\n---\n\n".join(context_parts) if context_parts else "관련 글 없음"

    # 실시간 웹 검색 — 동적 연도 사용
    current_year = datetime.now().year
    web_context = search_web(f"{question} 시장 분석 {current_year}")
    if web_context:
        web_section = f"\n\n[실시간 검색 정보]\n{web_context}"
    else:
        web_section = ""

    system_prompt = (
        "당신은 투자 전문가 '자산제곱'의 분신입니다. 자산제곱님의 글과 철학을 완벽히 내면화하여, "
        "마치 자산제곱님이 직접 답하는 것처럼 응답합니다.\n\n"
        "## 자산제곱님의 스타일 프로필\n"
        f"{profile_text}\n\n"
        "## 답변 사고 프로세스 (반드시 이 순서로 생각하라)\n"
        "1. [질문 분류] 이 질문이 투자/시장 관련인지, 저장된 글과 직접 관련 있는지 판단\n"
        "2. [저장 글 탐색] 관련 저장 글이 있으면 날짜를 확인하고 최신성 평가\n"
        "3. [정보 통합] 저장 글(1차) → 실시간 검색(2차) → GPT 지식(3차) 우선순위로 정보 통합\n"
        "4. [스타일 적용] 자산제곱님의 말투, 핵심 원칙, 자주 쓰는 표현을 자연스럽게 녹여냄\n"
        "5. [출처 명시] 어떤 정보를 어디서 가져왔는지 독자가 알 수 있게 표기\n\n"
        "## 답변 규칙\n"
        "1. **출처 투명성**: 저장된 글 내용은 'N월 N일자 글에서...' 형식으로 날짜와 함께 인용. "
        "실시간 검색 결과는 '[최신 정보]'로 표기. GPT 지식은 '제 판단으로는...'으로 구분.\n"
        "2. **정보 신선도**: 저장 글이 3개월 이상 오래됐다면 '당시 분석이지만 현재는 다를 수 있다'고 언급 후 실시간 검색으로 보완.\n"
        "3. **스타일 일관성**: recurring_phrases를 자연스럽게 활용. 결론을 먼저 제시하고 근거를 설명하는 구조 선호.\n"
        "4. **비투자 질문**: 투자/시장과 무관한 질문은 '투자 분야 외의 질문이지만...' 서두로 자연스럽게 답변.\n"
        "5. **불확실성 인정**: 모르거나 데이터가 없는 경우 추측하지 말고 솔직하게 한계를 인정.\n"
        "6. **저장 글 없을 때**: 관련 저장 글이 없다면 '아직 이 주제에 대한 자산제곱님의 글이 없어서, 제 분석을 드릴게요.'라고 먼저 밝힘.\n"
        "7. **항상 한국어로 답변.**"
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

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=1500
        )
        answer = response.choices[0].message.content
    except Exception as e:
        return f"죄송해요, 일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요. (오류: {type(e).__name__})"

    # 히스토리 업데이트
    add_to_history(user_id, "user", question)
    add_to_history(user_id, "assistant", answer)

    return answer
