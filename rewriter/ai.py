from openai import OpenAI
from config import OPENAI_API_KEY, TAVILY_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY)

# 유저별 대화 기록 저장 (메모리)
_chat_histories: dict[int, list] = {}

# AI 감지 우회용 공통 지침
_HUMAN_STYLE_RULES = """
글쓰기 규칙 (반드시 준수):
1. 문장 길이를 불규칙하게 섞어라. 아주 짧은 문장과 긴 문장을 번갈아 써라.
2. "사실", "솔직히", "그런데", "막상", "근데", "뭐랄까", "어찌 보면" 같은 구어체 표현을 자연스럽게 섞어라.
3. 서론-본론-결론의 완벽한 3단 구성을 피해라. 자유롭게 전개하라.
4. 필자의 개인적인 의견이나 감정을 군데군데 담아라. (예: "개인적으로 이 부분이 흥미로웠다", "솔직히 처음엔 잘 몰랐는데")
5. 같은 단어나 표현을 반복하지 말고, 동의어나 다른 표현으로 바꿔라.
6. AI가 자주 쓰는 "첫째", "둘째", "따라서", "결론적으로" 같은 형식적 표현을 피해라.
7. 문단 길이도 불규칙하게 써라. 한 줄짜리 문단도 괜찮다.
8. 필요하면 비유나 개인 경험담을 창작해서 넣어라.
"""


def search_web(query: str) -> str:
    """Tavily로 웹 검색. API 키 없으면 빈 문자열 반환."""
    if not TAVILY_API_KEY:
        return ""
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=TAVILY_API_KEY)
        results = tavily.search(
            query=query,
            max_results=5,
            search_depth="advanced"
        )
        texts = []
        for r in results.get("results", []):
            texts.append(f"[{r['title']}]\n{r['content'][:600]}")
        return "\n\n".join(texts)
    except Exception:
        return ""


def chat(message: str, user_id: int) -> str:
    """일반 GPT 대화. 유저별 대화 기록 유지."""
    if user_id not in _chat_histories:
        _chat_histories[user_id] = []

    _chat_histories[user_id].append({"role": "user", "content": message})

    # 최근 20턴만 유지
    if len(_chat_histories[user_id]) > 40:
        _chat_histories[user_id] = _chat_histories[user_id][-40:]

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": "당신은 친절하고 유능한 AI 어시스턴트입니다. 사용자의 질문에 자연스럽게 답해주세요."},
            *_chat_histories[user_id]
        ]
    )

    reply = response.choices[0].message.content
    _chat_histories[user_id].append({"role": "assistant", "content": reply})
    return reply


def clear_chat_history(user_id: int):
    """유저의 대화 기록 초기화."""
    _chat_histories.pop(user_id, None)


def rewrite(text: str, char_count: int = None) -> str:
    """
    주어진 텍스트를 AI 감지 우회 스타일로 리라이팅.
    char_count 지정 시 해당 글자수 목표로 작성.
    """
    length_instruction = ""
    if char_count:
        length_instruction = f"\n목표 글자수: {char_count}자 (±10% 허용). 반드시 해당 분량을 채워라."

    system_prompt = (
        "당신은 대학생 과제 전문 글쓰기 도우미입니다.\n"
        "아래 텍스트를 GPTZero, Turnitin 등 AI 감지 도구가 '사람이 쓴 글'로 인식하도록 완전히 리라이팅하세요.\n"
        "원문의 핵심 내용과 주장은 유지하되, 표현 방식을 완전히 바꿔야 합니다.\n\n"
        f"{_HUMAN_STYLE_RULES}"
        f"{length_instruction}"
    )

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"다음 글을 리라이팅해줘:\n\n{text}"}
        ],
        max_tokens=4000
    )

    return response.choices[0].message.content


def write_from_topic(topic: str, char_count: int = None) -> str:
    """
    주제를 받아 최신 정보 검색 + 개인 경험 창작으로 글 작성.
    char_count 지정 시 해당 글자수 목표로 작성.
    """
    # Tavily로 최신 정보 검색
    web_context = search_web(topic)
    if web_context:
        web_section = f"\n\n[참고할 최신 정보]\n{web_context}\n\n"
    else:
        web_section = ""

    length_instruction = ""
    if char_count:
        length_instruction = f"\n목표 글자수: {char_count}자 (±10% 허용). 반드시 해당 분량을 채워라."

    system_prompt = (
        "당신은 대학생 과제 전문 글쓰기 도우미입니다.\n"
        "주어진 주제로 GPTZero, Turnitin 등 AI 감지 도구가 '사람이 쓴 글'로 인식하는 글을 처음부터 작성하세요.\n"
        "최신 정보(검색 결과)와 창작한 개인 경험을 바탕으로 작성하세요.\n\n"
        f"{_HUMAN_STYLE_RULES}"
        f"{length_instruction}"
    )

    user_prompt = (
        f"주제: {topic}"
        f"{web_section}"
        "위 주제로 글을 작성해줘. 개인적인 경험이나 생각도 자연스럽게 섞어서."
    )

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        max_tokens=4000
    )

    return response.choices[0].message.content
