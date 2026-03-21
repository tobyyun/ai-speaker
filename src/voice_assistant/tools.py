"""
tools.py

Claude Tool Use를 위한 도구 정의 및 실행.
Claude가 스스로 판단하여 필요할 때 호출하는 외부 도구들.
모든 도구는 무료이며 별도 API 키가 필요 없다.
"""

import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path

# 도구 정의 (Claude API tool use 스펙)
TOOLS = [
    {
        "name": "get_current_time",
        "description": "현재 날짜와 시간을 반환합니다. 사용자가 시간, 날짜, 요일을 물어볼 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "web_search",
        "description": "인터넷에서 최신 정보를 검색합니다. 검색 내용에 따라 적절한 엔진을 선택하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 내용. 구체적으로 작성하세요.",
                },
                "engine": {
                    "type": "string",
                    "description": "검색 엔진 선택. duckduckgo: 일반 검색(뉴스, 날씨, 간단한 질문). tavily: 복합적인 질문, 여러 소스를 종합한 요약이 필요할 때. exa: 학술/기술/연구 자료, 특정 주제에 대한 깊은 정보가 필요할 때.",
                    "enum": ["duckduckgo", "tavily", "exa"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_weather",
        "description": "특정 도시의 현재 날씨와 예보를 가져옵니다. 사용자가 날씨, 기온, 비 여부 등을 물어볼 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "도시 이름 (예: Seoul, Busan, Tokyo, New York)",
                },
            },
            "required": ["city"],
        },
    },
    {
        "name": "calculate",
        "description": "수학 계산을 수행합니다. 사칙연산, 거듭제곱, 제곱근, 삼각함수, 단위 변환 등 숫자 계산이 필요할 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "계산할 수식 (Python 문법). 예: '2**10', 'math.sqrt(144)', '15 * 1.1', '100 / 3'",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_wikipedia",
        "description": "위키피디아에서 백과사전 정보를 가져옵니다. 역사, 과학, 인물, 지리, 동물, 식물 등 지식 질문에 사용하세요. 아이들의 호기심 질문에 좋습니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색할 주제 (한국어 또는 영어)",
                },
                "language": {
                    "type": "string",
                    "description": "위키피디아 언어 코드 (기본: ko)",
                    "enum": ["ko", "en", "ja"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "set_timer",
        "description": "타이머를 설정합니다. 요리, 공부, 운동 등 일정 시간 후 알림이 필요할 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "description": "타이머 시간 (초 단위). 예: 180 (3분), 300 (5분)",
                },
                "label": {
                    "type": "string",
                    "description": "타이머 이름 (예: '라면', '공부 시간')",
                },
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "get_exchange_rate",
        "description": "현재 환율 정보를 가져옵니다. 통화 변환이나 환율 확인이 필요할 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "base_currency": {
                    "type": "string",
                    "description": "기준 통화 코드 (예: USD, KRW, JPY, EUR)",
                },
                "target_currency": {
                    "type": "string",
                    "description": "대상 통화 코드 (예: KRW, USD, JPY, EUR)",
                },
            },
            "required": ["base_currency", "target_currency"],
        },
    },
    {
        "name": "get_assistant_info",
        "description": "비서의 이름과 정보를 가져옵니다. 사용자가 '이름이 뭐야?', '너 누구야?' 등 비서의 이름이나 정체를 물어볼 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "set_assistant_name",
        "description": "비서의 이름을 변경합니다. 사용자가 '이름을 X로 바꿔줘', '너 이름은 이제 X야' 등 이름 변경을 요청할 때 사용하세요. 웨이크워드도 자동으로 업데이트됩니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "새 이름 (예: '챱츄', '알파', '또리')",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_news",
        "description": "최신 뉴스를 가져옵니다. 사용자가 오늘/어제 뉴스, 최근 소식, 시사 이슈를 물어보거나, 심심해서 아무 얘기나 하자고 할 때도 사용하세요. 한국 뉴스는 naver, 글로벌/해외 뉴스는 gnews를 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "뉴스 검색어. 빈 문자열이면 주요 헤드라인을 가져옵니다.",
                },
                "source": {
                    "type": "string",
                    "description": "뉴스 소스. naver: 한국 뉴스 (기본), gnews: 글로벌/해외 뉴스",
                    "enum": ["naver", "gnews"],
                },
                "count": {
                    "type": "integer",
                    "description": "가져올 뉴스 수 (기본: 5, 최대: 10)",
                },
            },
            "required": [],
        },
    },
]

# 활성 타이머 저장
_active_timers: list[dict] = []

# 상태 파일 경로
_STATE_FILE = Path(__file__).parent.parent.parent / "assistant_state.json"

# 이름 변경 시 호출할 콜백 (VoiceAssistant에서 등록)
_on_name_changed_callback = None


def set_name_changed_callback(callback) -> None:
    """이름 변경 콜백 등록. VoiceAssistant가 초기화 시 호출."""
    global _on_name_changed_callback
    _on_name_changed_callback = callback


def load_state() -> dict:
    """상태 파일에서 설정 로드."""
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"name": "챱츄", "wakeword": "챱츄야"}


def save_state(state: dict) -> None:
    """상태를 파일에 저장."""
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"상태 저장 실패: {e}")


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """도구를 실행하고 결과를 문자열로 반환."""
    handlers = {
        "get_current_time": lambda _: _get_current_time(),
        "web_search": lambda inp: _web_search(
            inp.get("query", ""), inp.get("engine", "duckduckgo")
        ),
        "get_weather": lambda inp: _get_weather(inp.get("city", "Seoul")),
        "calculate": lambda inp: _calculate(inp.get("expression", "")),
        "get_wikipedia": lambda inp: _get_wikipedia(
            inp.get("query", ""), inp.get("language", "ko")
        ),
        "set_timer": lambda inp: _set_timer(
            inp.get("seconds", 60), inp.get("label", "타이머")
        ),
        "get_exchange_rate": lambda inp: _get_exchange_rate(
            inp.get("base_currency", "USD"), inp.get("target_currency", "KRW")
        ),
        "get_assistant_info": lambda _: _get_assistant_info(),
        "set_assistant_name": lambda inp: _set_assistant_name(inp.get("name", "")),
        "get_news": lambda inp: _get_news(
            inp.get("query", ""), inp.get("source", "naver"), inp.get("count", 5)
        ),
    }

    handler = handlers.get(tool_name)
    if handler:
        return handler(tool_input)
    return f"알 수 없는 도구: {tool_name}"


# ─── 도구 구현 ───────────────────────────────────────────


def _get_current_time() -> str:
    """현재 날짜와 시간 반환."""
    now = datetime.now()
    weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    weekday = weekdays[now.weekday()]

    result = (
        f"현재 시각: {now.strftime('%Y년 %m월 %d일')} {weekday} "
        f"{now.strftime('%p %I시 %M분').replace('AM', '오전').replace('PM', '오후')}"
    )
    logging.debug(f"도구 [get_current_time]: {result}")
    return result


def _web_search(query: str, engine: str = "duckduckgo") -> str:
    """검색 엔진 라우터. 엔진에 따라 적절한 검색 서비스를 호출.

    폴백 체인: 지정 엔진 실패 → DuckDuckGo (항상 가용)
    """
    if not query:
        return "검색어가 비어있습니다."

    engine = engine.lower().strip()

    # Tavily 시도 (API 키가 있을 때만)
    if engine == "tavily":
        result = _search_tavily(query)
        if result:
            return result
        logging.debug("Tavily 사용 불가, DuckDuckGo로 폴백")

    # Exa 시도 (API 키가 있을 때만)
    if engine == "exa":
        result = _search_exa(query)
        if result:
            return result
        logging.debug("Exa 사용 불가, DuckDuckGo로 폴백")

    # DuckDuckGo (기본, 항상 가용)
    return _search_duckduckgo(query)


def _search_duckduckgo(query: str) -> str:
    """DuckDuckGo 검색 (무료, API 키 불필요)."""
    logging.info(f"검색 [DuckDuckGo]: '{query}'")
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))

        if not results:
            return f"'{query}'에 대한 검색 결과가 없습니다."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"{i}. {r.get('title', '')}: {r.get('body', '')}")

        return "\n".join(parts)

    except ImportError:
        return "duckduckgo-search 패키지가 필요합니다."
    except Exception as e:
        logging.error(f"DuckDuckGo 오류: {e}")
        return f"검색 오류: {e}"


def _search_tavily(query: str) -> str | None:
    """Tavily AI 검색 (월 1,000회 무료). AI 에이전트에 최적화된 요약 제공.

    Returns:
        검색 결과 문자열, 또는 사용 불가 시 None
    """
    import os
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return None

    logging.info(f"검색 [Tavily]: '{query}'")
    try:
        import requests

        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 3,
                "include_answer": True,
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logging.warning(f"Tavily API 오류: {resp.status_code}")
            return None

        data = resp.json()

        # Tavily의 AI 요약 답변 (가장 유용)
        answer = data.get("answer", "")
        results = data.get("results", [])

        parts = []
        if answer:
            parts.append(f"요약: {answer}")

        for i, r in enumerate(results[:3], 1):
            title = r.get("title", "")
            content = r.get("content", "")[:200]
            parts.append(f"{i}. {title}: {content}")

        return "\n".join(parts) if parts else None

    except Exception as e:
        logging.error(f"Tavily 오류: {e}")
        return None


def _search_exa(query: str) -> str | None:
    """Exa 시맨틱 검색 (가입 시 ~2,000회 무료). 학술/기술 리서치에 강점.

    Returns:
        검색 결과 문자열, 또는 사용 불가 시 None
    """
    import os
    api_key = os.environ.get("EXA_API_KEY", "")
    if not api_key:
        return None

    logging.info(f"검색 [Exa]: '{query}'")
    try:
        import requests

        resp = requests.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "num_results": 3,
                "type": "auto",
                "contents": {
                    "text": {"max_characters": 300},
                },
            },
            timeout=15,
        )

        if resp.status_code != 200:
            logging.warning(f"Exa API 오류: {resp.status_code}")
            return None

        data = resp.json()
        results = data.get("results", [])

        if not results:
            return None

        parts = []
        for i, r in enumerate(results[:3], 1):
            title = r.get("title", "")
            text = r.get("text", "")[:200]
            parts.append(f"{i}. {title}: {text}")

        return "\n".join(parts) if parts else None

    except Exception as e:
        logging.error(f"Exa 오류: {e}")
        return None


def _get_weather(city: str) -> str:
    """wttr.in으로 날씨 정보 조회 (무료, API 키 불필요)."""
    logging.info(f"날씨 조회 중: {city}")
    try:
        import requests

        # wttr.in JSON API
        resp = requests.get(
            f"https://wttr.in/{city}?format=j1",
            headers={"Accept-Language": "ko"},
            timeout=10,
        )

        if resp.status_code != 200:
            return f"{city} 날씨를 가져올 수 없습니다."

        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        forecast = data.get("weather", [])

        temp = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc_ko = current.get("lang_ko", [{}])
        desc = desc_ko[0].get("value", current.get("weatherDesc", [{}])[0].get("value", "")) if desc_ko else ""
        wind = current.get("windspeedKmph", "?")

        result = f"{city} 현재 날씨: {desc}, 기온 {temp}°C (체감 {feels}°C), 습도 {humidity}%, 바람 {wind}km/h"

        # 오늘 예보
        if forecast:
            today = forecast[0]
            max_t = today.get("maxtempC", "?")
            min_t = today.get("mintempC", "?")
            result += f"\n오늘 최고 {max_t}°C / 최저 {min_t}°C"

            # 내일 예보
            if len(forecast) > 1:
                tomorrow = forecast[1]
                t_max = tomorrow.get("maxtempC", "?")
                t_min = tomorrow.get("mintempC", "?")
                t_desc_ko = tomorrow.get("hourly", [{}])[4].get("lang_ko", [{}])
                t_desc = t_desc_ko[0].get("value", "") if t_desc_ko else ""
                result += f"\n내일: {t_desc}, 최고 {t_max}°C / 최저 {t_min}°C"

        logging.debug(f"도구 [get_weather]: {result}")
        return result

    except Exception as e:
        logging.error(f"날씨 조회 오류: {e}")
        return f"날씨 조회 오류: {e}"


def _calculate(expression: str) -> str:
    """수학 계산 (안전한 eval)."""
    if not expression:
        return "계산식이 비어있습니다."

    logging.info(f"계산 중: {expression}")
    try:
        # 안전한 네임스페이스 (math 함수만 허용)
        safe_globals = {"__builtins__": {}}
        safe_locals = {
            "math": math,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "pi": math.pi,
            "e": math.e,
            "log": math.log,
            "log10": math.log10,
            "abs": abs,
            "round": round,
            "pow": pow,
            "min": min,
            "max": max,
        }

        result = eval(expression, safe_globals, safe_locals)

        # 결과 포맷팅
        if isinstance(result, float):
            if result == int(result):
                formatted = str(int(result))
            else:
                formatted = f"{result:.6g}"
        else:
            formatted = str(result)

        logging.debug(f"도구 [calculate]: {expression} = {formatted}")
        return f"{expression} = {formatted}"

    except Exception as e:
        return f"계산 오류 ({expression}): {e}"


def _get_wikipedia(query: str, language: str = "ko") -> str:
    """위키피디아 API로 백과사전 정보 조회."""
    if not query:
        return "검색어가 비어있습니다."

    logging.info(f"위키피디아 검색: '{query}' ({language})")
    try:
        import requests

        # 위키피디아 검색 API
        resp = requests.get(
            f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{query}",
            headers={"User-Agent": "ai-speaker/1.0"},
            timeout=10,
        )

        if resp.status_code == 404:
            # 검색으로 폴백
            search_resp = requests.get(
                f"https://{language}.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 3,
                    "format": "json",
                },
                timeout=10,
            )
            search_data = search_resp.json()
            titles = search_data[1] if len(search_data) > 1 else []

            if not titles:
                return f"'{query}'에 대한 위키피디아 문서를 찾을 수 없습니다."

            # 첫 번째 결과로 재시도
            resp = requests.get(
                f"https://{language}.wikipedia.org/api/rest_v1/page/summary/{titles[0]}",
                headers={"User-Agent": "ai-speaker/1.0"},
                timeout=10,
            )

        if resp.status_code != 200:
            return f"위키피디아에서 '{query}'를 찾을 수 없습니다."

        data = resp.json()
        title = data.get("title", query)
        extract = data.get("extract", "")

        # 너무 긴 내용은 잘라서 반환
        if len(extract) > 500:
            extract = extract[:500] + "..."

        result = f"[{title}] {extract}"
        logging.debug(f"도구 [get_wikipedia]: {title} ({len(extract)}자)")
        return result

    except Exception as e:
        logging.error(f"위키피디아 오류: {e}")
        return f"위키피디아 조회 오류: {e}"


def _set_timer(seconds: int, label: str = "타이머") -> str:
    """백그라운드 타이머 설정."""
    import threading

    if seconds <= 0:
        return "타이머 시간은 0보다 커야 합니다."
    if seconds > 7200:  # 최대 2시간
        return "타이머는 최대 2시간(7200초)까지 설정할 수 있습니다."

    logging.info(f"타이머 설정: {label} ({seconds}초)")

    def _timer_done():
        """타이머 완료 콜백."""
        logging.info(f"타이머 완료: {label} ({seconds}초)")
        # 터미널 벨 소리
        print(f"\a\n*** 타이머 완료: {label} ***\n")

    timer = threading.Timer(seconds, _timer_done)
    timer.daemon = True
    timer.start()

    _active_timers.append({"label": label, "seconds": seconds, "timer": timer})

    # 사람이 읽기 쉬운 시간
    if seconds >= 3600:
        time_str = f"{seconds // 3600}시간 {(seconds % 3600) // 60}분"
    elif seconds >= 60:
        time_str = f"{seconds // 60}분 {seconds % 60}초" if seconds % 60 else f"{seconds // 60}분"
    else:
        time_str = f"{seconds}초"

    return f"'{label}' 타이머를 {time_str} 후로 설정했습니다."


def _get_exchange_rate(base: str, target: str) -> str:
    """환율 정보 조회 (frankfurter.app, 무료)."""
    base = base.upper()
    target = target.upper()

    logging.info(f"환율 조회: {base} -> {target}")
    try:
        import requests

        resp = requests.get(
            f"https://api.frankfurter.app/latest?from={base}&to={target}",
            timeout=10,
        )

        if resp.status_code != 200:
            return f"{base}/{target} 환율을 가져올 수 없습니다."

        data = resp.json()
        rate = data.get("rates", {}).get(target)

        if rate is None:
            return f"{base}/{target} 환율 정보가 없습니다."

        date = data.get("date", "")
        result = f"1 {base} = {rate:,.2f} {target} ({date} 기준)"
        logging.debug(f"도구 [get_exchange_rate]: {result}")
        return result

    except Exception as e:
        logging.error(f"환율 조회 오류: {e}")
        return f"환율 조회 오류: {e}"


# ─── 뉴스 도구 ───────────────────────────────────────────


def _get_news(query: str = "", source: str = "naver", count: int = 5) -> str:
    """뉴스 검색 라우터. 소스에 따라 네이버 또는 GNews를 호출.

    폴백 체인: 지정 소스 실패 → GNews → DuckDuckGo 뉴스
    """
    count = min(max(count, 1), 10)

    if source == "naver":
        result = _news_naver(query, count)
        if result:
            return result
        logging.debug("네이버 뉴스 사용 불가, GNews로 폴백")

    result = _news_gnews(query, count)
    if result:
        return result

    # 최종 폴백: DuckDuckGo 뉴스 검색
    logging.debug("GNews 사용 불가, DuckDuckGo 뉴스로 폴백")
    return _news_duckduckgo(query or "오늘 뉴스", count)


def _news_naver(query: str, count: int) -> str | None:
    """네이버 뉴스 검색 API (일 25,000회 무료).

    네이버 개발자센터에서 Client ID/Secret 발급 필요.
    https://developers.naver.com/apps/
    """
    import os
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        return None

    # 검색어가 없으면 "오늘 뉴스"로 검색
    search_query = query if query else "오늘 주요 뉴스"

    logging.info(f"뉴스 [네이버]: '{search_query}'")
    try:
        import requests
        import re

        resp = requests.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={
                "query": search_query,
                "display": count,
                "sort": "date",  # 최신순
            },
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            timeout=10,
        )

        if resp.status_code != 200:
            logging.warning(f"네이버 뉴스 API 오류: {resp.status_code}")
            return None

        data = resp.json()
        items = data.get("items", [])

        if not items:
            return f"'{search_query}'에 대한 네이버 뉴스가 없습니다."

        parts = []
        for i, item in enumerate(items[:count], 1):
            # HTML 태그 제거
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))
            desc = re.sub(r"<[^>]+>", "", item.get("description", ""))
            pub_date = item.get("pubDate", "")

            parts.append(f"{i}. [{title}] {desc} ({pub_date})")

        logging.debug(f"도구 [naver_news]: {len(items)}건")
        return "\n".join(parts)

    except Exception as e:
        logging.error(f"네이버 뉴스 오류: {e}")
        return None


def _news_gnews(query: str, count: int) -> str | None:
    """GNews API (일 100회 무료).

    https://gnews.io/ 에서 API 키 발급.
    """
    import os
    api_key = os.environ.get("GNEWS_API_KEY", "")

    if not api_key:
        return None

    logging.info(f"뉴스 [GNews]: '{query or '헤드라인'}'")
    try:
        import requests

        if query:
            # 키워드 검색
            url = "https://gnews.io/api/v4/search"
            params = {
                "q": query,
                "lang": "ko",
                "max": count,
                "apikey": api_key,
            }
        else:
            # 주요 헤드라인
            url = "https://gnews.io/api/v4/top-headlines"
            params = {
                "lang": "ko",
                "country": "kr",
                "max": count,
                "apikey": api_key,
            }

        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code != 200:
            logging.warning(f"GNews API 오류: {resp.status_code}")
            return None

        data = resp.json()
        articles = data.get("articles", [])

        if not articles:
            return None

        parts = []
        for i, article in enumerate(articles[:count], 1):
            title = article.get("title", "")
            desc = article.get("description", "")[:150]
            source_name = article.get("source", {}).get("name", "")
            published = article.get("publishedAt", "")[:10]

            parts.append(f"{i}. [{source_name}] {title} - {desc} ({published})")

        logging.debug(f"도구 [gnews]: {len(articles)}건")
        return "\n".join(parts)

    except Exception as e:
        logging.error(f"GNews 오류: {e}")
        return None


def _news_duckduckgo(query: str, count: int) -> str:
    """DuckDuckGo 뉴스 검색 (무료, API 키 불필요). 최종 폴백."""
    logging.info(f"뉴스 [DuckDuckGo]: '{query}'")
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.news(query, max_results=count))

        if not results:
            return f"'{query}'에 대한 뉴스가 없습니다."

        parts = []
        for i, r in enumerate(results[:count], 1):
            title = r.get("title", "")
            body = r.get("body", "")[:150]
            source = r.get("source", "")
            date = r.get("date", "")[:10]
            parts.append(f"{i}. [{source}] {title} - {body} ({date})")

        return "\n".join(parts)

    except Exception as e:
        logging.error(f"DuckDuckGo 뉴스 오류: {e}")
        return f"뉴스 조회 오류: {e}"


# ─── 비서 이름/정보 도구 ─────────────────────────────────


def _get_assistant_info() -> str:
    """비서의 이름과 정보를 반환."""
    state = load_state()
    name = state.get("name", "챱츄")
    wakeword = state.get("wakeword", f"{name}야")
    return (
        f"이름: {name}\n"
        f"웨이크워드: '{wakeword}'\n"
        f"역할: 한국어 음성 비서\n"
        f"LLM: Claude Sonnet"
    )


def _set_assistant_name(new_name: str) -> str:
    """비서의 이름을 변경하고 웨이크워드를 업데이트."""
    if not new_name or not new_name.strip():
        return "이름이 비어있습니다."

    new_name = new_name.strip()
    new_wakeword = f"{new_name}야"

    state = load_state()
    old_name = state.get("name", "챱츄")

    state["name"] = new_name
    state["wakeword"] = new_wakeword
    save_state(state)

    logging.info(f"비서 이름 변경: '{old_name}' → '{new_name}', 웨이크워드: '{new_wakeword}'")

    # 런타임 웨이크워드 업데이트 콜백
    if _on_name_changed_callback:
        _on_name_changed_callback(new_name, new_wakeword)

    return (
        f"이름이 '{new_name}'(으)로 변경되었습니다. "
        f"이제 '{new_wakeword}'라고 불러주세요."
    )
