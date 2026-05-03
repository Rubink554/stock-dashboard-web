from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def load_dotenv(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#") or "=" not in clean:
            continue
        key, value = clean.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def ai_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY", "").strip())


def ai_status() -> dict:
    return {
        "enabled": ai_enabled(),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "provider": "openai",
        "env_key": "OPENAI_API_KEY",
        "web_search": False,
    }


def summarize_news_with_ai(title: str, summary: str, tags: list[str] | None = None) -> dict | None:
    if not ai_enabled():
        return None
    prompt = {
        "title": title,
        "summary": summary,
        "tags": tags or [],
        "instruction": "한국어로 투자자가 빠르게 이해할 수 있게 요약하세요. JSON만 반환하세요: ai_summary, sentiment(positive/negative/neutral), tags 배열.",
    }
    text = call_openai_json(prompt)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    sentiment = payload.get("sentiment")
    if sentiment not in {"positive", "negative", "neutral"}:
        sentiment = "neutral"
    clean_tags = [str(tag) for tag in payload.get("tags", []) if str(tag).strip()][:4]
    return {
        "ai_summary": str(payload.get("ai_summary") or summary or title)[:260],
        "sentiment": sentiment,
        "tags": clean_tags or (tags or ["일반"]),
    }


def call_openai_json(payload: dict) -> str:
    result = call_openai_json_with_sources(payload, use_web=False, timeout=12)
    return result.get("text", "")


def call_openai_json_with_sources(payload: dict, use_web: bool = False, timeout: int = 30) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip()
    request_body = {
        "model": model,
        "instructions": "You are a careful Korean stock research assistant. Output only valid JSON.",
        "input": json.dumps(payload, ensure_ascii=False),
        "text": {"format": {"type": "json_object"}},
    }
    if use_web:
        request_body["tools"] = [{"type": "web_search"}]
        request_body["tool_choice"] = "auto"
        request_body["include"] = ["web_search_call.action.sources"]
    body = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        return {"text": "", "sources": [], "error": f"OpenAI HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"text": "", "sources": [], "error": str(exc)[:500]}
    return {"text": extract_output_text(data), "sources": extract_sources(data), "status": data.get("status")}


def extract_output_text(data: dict) -> str:
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    return data.get("output_text", "") or ""


def extract_sources(data: dict) -> list[dict]:
    sources = []
    seen = set()
    for source in data.get("sources", []) or []:
        if not isinstance(source, dict):
            continue
        url = source.get("url")
        if url and url not in seen:
            seen.add(url)
            sources.append({"title": source.get("title") or url, "url": url})
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            for ann in content.get("annotations", []) or []:
                url = ann.get("url") if isinstance(ann, dict) else None
                if url and url not in seen:
                    seen.add(url)
                    sources.append({"title": ann.get("title") or url, "url": url})
        action = item.get("action", {})
        if isinstance(action, dict):
            for source in action.get("sources", []) or []:
                url = source.get("url") if isinstance(source, dict) else None
                if url and url not in seen:
                    seen.add(url)
                    sources.append({"title": source.get("title") or url, "url": url})
    return sources[:10]



def summarize_stock_news_bundle_with_ai(ticker: str, company_name: str | None, items: list[dict]) -> dict | None:
    compact_items = []
    for item in (items or [])[:10]:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        compact_items.append({
            "title": title[:220],
            "publisher": item.get("publisher"),
            "published_at": item.get("published_at"),
            "summary": str(item.get("ai_summary") or item.get("summary") or "")[:280],
            "url": item.get("url"),
        })
    if not compact_items:
        return None
    if not ai_enabled():
        return fallback_news_bundle_summary(ticker, compact_items)
    prompt = {
        "ticker": ticker,
        "company_name": company_name or ticker,
        "news_items": compact_items,
        "rules": [
            "Analyze only the supplied news_items. Do not invent news, prices, earnings figures, or catalysts.",
            "If the supplied articles are weak or unrelated, say 데이터 부족.",
            "Output Korean only and valid JSON only.",
            "Keep it concise for Korean retail investors.",
        ],
        "output_schema": {
            "headline": "one-line summary",
            "sentiment": "positive/negative/neutral/mixed",
            "key_issues": ["3 short bullets"],
            "watch_points": ["2-4 practical check points"],
            "reason": "why these articles matter",
        },
    }
    text = call_openai_json(prompt)
    if not text:
        return fallback_news_bundle_summary(ticker, compact_items)
    try:
        payload = json.loads(text)
    except Exception:
        return fallback_news_bundle_summary(ticker, compact_items)
    return normalize_news_bundle_summary(payload, compact_items)


def normalize_news_bundle_summary(payload: dict, items: list[dict]) -> dict:
    def clean_text(value, fallback="데이터 부족", limit=260):
        value = str(value or fallback).strip()
        return value[:limit] if value else fallback

    def clean_list(value, limit=4):
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:180] for item in value if str(item).strip()][:limit]

    sentiment = str(payload.get("sentiment") or "neutral").lower()
    if sentiment not in {"positive", "negative", "neutral", "mixed"}:
        sentiment = "neutral"
    return {
        "source": "gpt-app-news",
        "headline": clean_text(payload.get("headline"), limit=220),
        "sentiment": sentiment,
        "key_issues": clean_list(payload.get("key_issues"), 4) or [clean_text(items[0].get("title"), limit=160)],
        "watch_points": clean_list(payload.get("watch_points"), 4),
        "reason": clean_text(payload.get("reason"), limit=260),
        "articles": items[:5],
    }


def korean_news_issue(title: str, ticker: str = "") -> str:
    raw = str(title or "").strip()
    lower = raw.lower()
    company = ticker or "해당 종목"
    rules = [
        (["earnings", "quarter", "revenue", "profit", "eps", "guidance"], f"{company} 실적·가이던스 관련 이슈입니다."),
        (["contract", "order", "deal", "partnership", "home office", "border", "government", "defense"], f"{company} 수주·정부계약 가능성과 관련된 뉴스입니다."),
        (["buyback", "dividend", "shareholder"], f"{company} 주주환원 정책 관련 이슈입니다."),
        (["upgrade", "downgrade", "target", "rating", "analyst"], f"{company} 애널리스트 의견 또는 목표가 관련 뉴스입니다."),
        (["prediction", "forecast", "outlook", "may ", "will be", "could"], f"{company} 향후 주가 전망과 기대감 관련 기사입니다."),
        (["lawsuit", "probe", "investigation", "regulation", "court", "ban"], f"{company} 규제·소송·정책 리스크 관련 뉴스입니다."),
        (["ai", "chip", "semiconductor", "cloud", "software"], f"{company} AI·기술 성장 테마와 연결된 뉴스입니다."),
        (["economy", "inflation", "fed", "rate", "jobs", "consumer", "tariff"], "미국 경제·정책 환경이 종목에 미칠 영향과 관련된 기사입니다."),
        (["stock to buy", "good stock", "top stock", "best stock"], f"{company} 투자 매력도 평가 기사입니다."),
        (["falls", "drops", "slumps", "weak", "miss", "cut"], f"{company} 주가 약세 또는 부정적 이벤트 관련 뉴스입니다."),
        (["surge", "soar", "rally", "strong", "beat", "record"], f"{company} 긍정적 실적·주가 모멘텀 관련 뉴스입니다."),
    ]
    for words, message in rules:
        if any(word in lower for word in words):
            return message
    if raw:
        cleaned = raw.replace(ticker, company).strip()
        return f"{company} 관련 기사입니다: {cleaned[:80]}"
    return "핵심 이슈 없음"


def compact_korean_issues(items: list[dict], ticker: str, limit: int = 4) -> list[str]:
    issues = []
    seen = set()
    for item in items:
        issue = korean_news_issue(str(item.get("title") or item.get("summary") or ""), ticker)
        key = issue.lower()
        if key in seen:
            continue
        seen.add(key)
        issues.append(issue)
        if len(issues) >= limit:
            break
    return issues or ["핵심 이슈 없음"]
def fallback_news_bundle_summary(ticker: str, items: list[dict]) -> dict:
    issues = compact_korean_issues(items, ticker, limit=4)
    return {
        "source": "rule-news-summary",
        "headline": f"{ticker} 관련 뉴스 {len(items)}건을 한글 이슈로 정리했습니다.",
        "sentiment": "neutral",
        "key_issues": issues,
        "watch_points": ["원문 제목 기반의 규칙 요약입니다.", "중요 뉴스는 원문을 열어 세부 내용을 확인하세요."],
        "reason": "AI 결제/한도 없이도 읽기 쉽도록 기사 제목을 한글 이슈로 분류했습니다.",
        "articles": items[:5],
    }

def analyze_stock_with_ai(stock: dict, metrics: dict, prices: list[dict] | None = None, news: list[dict] | None = None) -> dict | None:
    if not ai_enabled():
        return {"source": "error", "error": "OPENAI_API_KEY가 설정되지 않았습니다."}
    recent_prices = (prices or [])[-60:]
    recent_news = (news or [])[:8]
    analysis_question = build_stock_analysis_question(stock, metrics, recent_prices, recent_news)
    prompt = {
        "question": analysis_question,
        "ticker": stock.get("ticker") or metrics.get("ticker") or stock.get("external_symbol"),
        "company_name": stock.get("name") or stock.get("nameEn") or stock.get("nameKr"),
        "local_chart_context": build_local_chart_context(recent_prices),
        "stock_data": stock,
        "metrics_data": metrics,
        "recent_prices": recent_prices,
        "recent_news": recent_news,
        "instruction": (
            "웹검색을 사용해서 해당 종목의 최신 주가 흐름, 최근 핵심 이슈, 주요 밸류에이션 지표(PER/PBR/ROE/Forward PE), "
            "애널리스트 목표가 또는 컨센서스가 확인되는지 찾아라. 로컬 페이지에 있는 값만 요약하지 말고, 웹에서 확인한 정보 중심으로 답하라. "
            "단, 매수/매도 단정이나 수익 보장은 금지한다. 한국어 JSON만 반환하라. "
            "필드: summary, trend, strategy, strategies{conservative,neutral,aggressive}, risks 배열, checklist 배열, data_points 배열. "
            "data_points는 label,value,note 형식으로 3~6개. 각 전략은 trigger, action, invalidation, comment 필드를 가진다."
        ),
    }
    result = call_openai_json_with_sources(prompt, use_web=False, timeout=45)
    if not result.get("text"):
        return {"source": "error", "error": result.get("error") or "GPT 웹검색 응답을 받지 못했습니다.", "question": analysis_question}
    try:
        payload = json.loads(result["text"])
    except Exception:
        return {"source": "error", "error": "GPT 응답을 JSON으로 해석하지 못했습니다.", "question": analysis_question}
    normalized = normalize_stock_analysis(payload)
    normalized["question"] = analysis_question
    normalized["source"] = "gpt-app-data"
    normalized["sources"] = []
    return normalized


def analyze_stock_research_with_ai(stock: dict, metrics: dict) -> dict | None:
    if not ai_enabled():
        return {"source": "error", "error": "OPENAI_API_KEY가 설정되지 않았습니다."}
    ticker = stock.get("ticker") or metrics.get("ticker") or stock.get("external_symbol") or stock.get("name") or "선택 종목"
    company_name = stock.get("name") or stock.get("nameEn") or stock.get("nameKr") or ticker
    research_question = (
        f"{ticker}({company_name})를 한국 개인투자자 관점에서 리서치 브리핑처럼 분석해줘. "
        "앱 화면의 일부 데이터가 비어 있을 수 있으므로, 정확한 최신 가격/목표가/실적일/공매도 수치처럼 확인이 필요한 숫자는 임의로 만들지 말고 데이터 없음으로 표시해. "
        "다만 사업 구조, 업황, 투자 포인트, 리스크, 확인해야 할 촉매는 티커와 회사명을 기준으로 정리해. "
        "매수/매도 지시는 금지하고 확률적 표현만 사용해. 단기 트레이딩 관점과 중기 투자 관점을 분리해."
    )
    prompt = {
        "question": research_question,
        "ticker": ticker,
        "company_name": company_name,
        "known_metrics": metrics,
        "instruction": (
            "한국어 JSON만 반환하라. 필드: summary, short_term_view, medium_term_view, fundamental_quality, "
            "technical_momentum, valuation, catalyst, short_squeeze_potential, dilution_or_balance_sheet_risk, "
            "strategy, strategies{conservative,neutral,aggressive}, risks 배열, checklist 배열, data_points 배열. "
            "data_points는 label,value,note 형식으로 3~6개. 알 수 없는 값은 반드시 '데이터 없음'이라고 써라. "
            "각 전략은 trigger, action, invalidation, comment 필드를 가진다. 개인화된 투자 조언이나 매수/매도 명령은 하지 말라."
        ),
    }
    result = call_openai_json_with_sources(prompt, use_web=False, timeout=45)
    if not result.get("text"):
        return {"source": "error", "error": result.get("error") or "GPT 리서치 응답을 받지 못했습니다.", "question": research_question}
    try:
        payload = json.loads(result["text"])
    except Exception:
        return {"source": "error", "error": "GPT 응답을 JSON으로 해석하지 못했습니다.", "question": research_question}
    normalized = normalize_stock_analysis(payload)
    normalized["question"] = research_question
    normalized["source"] = "gpt-research"
    normalized["sources"] = []
    return normalized
def build_local_chart_context(prices: list[dict]) -> str:
    closes = [item.get("close") for item in prices if isinstance(item.get("close"), (int, float))]
    if len(closes) < 20:
        return "로컬 차트 데이터 부족. 웹검색 기반으로 판단 필요."
    recent = closes[-1]
    avg20 = sum(closes[-20:]) / 20
    high = max(closes[-60:])
    low = min(closes[-60:])
    return f"최근 종가 {recent:.2f}, 20일 평균 {avg20:.2f}, 최근 60개 관측치 고점 {high:.2f}, 저점 {low:.2f}"


def build_stock_analysis_question(stock: dict, metrics: dict, prices: list[dict], news: list[dict]) -> str:
    ticker = stock.get("ticker") or stock.get("external_symbol") or stock.get("name") or "선택 종목"
    closes = [item.get("close") for item in prices if isinstance(item.get("close"), (int, float))]
    price_context = "가격 이력 부족"
    if len(closes) >= 20:
        recent = closes[-1]
        avg20 = sum(closes[-20:]) / 20
        high = max(closes[-60:]) if closes else recent
        low = min(closes[-60:]) if closes else recent
        price_context = f"최근 종가 {recent:.2f}, 20일 평균 {avg20:.2f}, 최근 구간 고점 {high:.2f}, 저점 {low:.2f}"
    news_titles = [str(item.get("title") or "").strip() for item in news if str(item.get("title") or "").strip()][:5]
    return (
        f"{ticker}에 대해 웹검색으로 최신 정보를 확인해서 매매 전 점검용 분석을 해줘. "
        f"로컬 차트 참고값: {price_context}. "
        f"로컬 수집 뉴스 제목: {' | '.join(news_titles) if news_titles else '최근 2일 내 수집 뉴스 없음'}. "
        "페이지에 이미 있는 값만 요약하지 말고, 웹에서 확인한 최근 이슈, 밸류에이션 지표, 목표가/컨센서스 가능 여부를 찾아서 "
        "보수적/중립/공격적 3단 전략과 각 전략의 진입 조건, 대응, 무효화 기준을 제시해줘."
    )


def normalize_stock_analysis(payload: dict) -> dict:
    def clean_list(value, limit=4):
        if not isinstance(value, list):
            return []
        return [str(item).strip()[:180] for item in value if str(item).strip()][:limit]

    def clean_data_points(value, limit=6):
        if not isinstance(value, list):
            return []
        rows = []
        for item in value:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            val = str(item.get("value") or "").strip()
            note = str(item.get("note") or "").strip()
            if label and val:
                rows.append({"label": label[:60], "value": val[:80], "note": note[:140]})
            if len(rows) >= limit:
                break
        return rows

    def clean_strategy(value, fallback):
        value = value if isinstance(value, dict) else {}
        return {
            "trigger": str(value.get("trigger") or fallback["trigger"])[:180],
            "action": str(value.get("action") or fallback["action"])[:180],
            "invalidation": str(value.get("invalidation") or fallback["invalidation"])[:180],
            "comment": str(value.get("comment") or fallback["comment"])[:220],
        }

    fallbacks = default_strategies()
    raw_strategies = payload.get("strategies") if isinstance(payload.get("strategies"), dict) else {}
    return {
        "summary": str(payload.get("summary") or "AI 분석을 생성하지 못했습니다.")[:360],
        "trend": str(payload.get("trend") or "차트 추세는 추가 확인이 필요합니다.")[:240],
        "strategy": str(payload.get("strategy") or "아래 3단 시나리오를 기준으로 검토하세요.")[:260],
        "strategies": {
            "conservative": clean_strategy(raw_strategies.get("conservative"), fallbacks["conservative"]),
            "neutral": clean_strategy(raw_strategies.get("neutral"), fallbacks["neutral"]),
            "aggressive": clean_strategy(raw_strategies.get("aggressive"), fallbacks["aggressive"]),
        },
        "risks": clean_list(payload.get("risks"), 4),
        "checklist": clean_list(payload.get("checklist"), 5),
        "data_points": clean_data_points(payload.get("data_points")),
    }


def default_strategies() -> dict:
    return {
        "conservative": {
            "trigger": "주요 지지선 확인 후 변동성이 낮아질 때",
            "action": "소량 분할 접근 또는 관망",
            "invalidation": "지지선 이탈 또는 거래량 동반 하락",
            "comment": "확인된 데이터가 부족할수록 보수적으로 접근합니다.",
        },
        "neutral": {
            "trigger": "20일 평균 회복 또는 박스권 상단 돌파 확인",
            "action": "분할 진입 후 손절 기준을 짧게 설정",
            "invalidation": "돌파 실패 후 이전 저점 재이탈",
            "comment": "차트 확인과 지표 채움 상태를 함께 봅니다.",
        },
        "aggressive": {
            "trigger": "강한 거래량과 함께 단기 저항 돌파 시",
            "action": "작은 비중으로 빠른 추세 추종",
            "invalidation": "돌파 가격 아래로 빠르게 되돌림",
            "comment": "변동성이 크므로 손절 기준이 먼저 정해져야 합니다.",
        },
    }



