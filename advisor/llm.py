"""LLM 호출. 회사별 어댑터를 같은 모양(Provider)으로 두고 settings.LLM_PROVIDER로 고른다.

- 지금은 OpenAI(Responses API)만 있다. 다른 회사는 Provider를 하나 더 만들어 PROVIDERS에 넣으면 된다
  (실제 호출로 확인한 뒤에 추가한다).
- 네트워크로 나가는 길은 _send() 하나뿐이다. 테스트는 이것을 막거나 가짜로 바꾼다(config/test_runner.py).
- 키는 헤더로만 보낸다(주소에 넣지 않는다). 키·질문·답변·응답 본문은 로그와 오류 메시지에 남기지 않는다.
  로그에는 회사, 모델, HTTP 상태, 오류 종류, 걸린 시간만 남긴다.
"""

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """kind: timeout / network / auth / rate_limit / http / bad_response / empty / disabled.
    메시지에는 응답 본문이나 키를 넣지 않는다."""

    def __init__(self, kind, status=None):
        super().__init__(kind)
        self.kind = kind
        self.status = status


@dataclass
class Message:
    role: str  # "user" / "assistant"
    content: str


class Provider:
    """회사별 어댑터. request()는 (주소, 헤더, 본문 dict), parse()는 응답 JSON에서 답변 글을 꺼낸다."""

    name = ""

    def request(self, *, model, api_key, system, messages, max_output_tokens, reasoning_effort):
        raise NotImplementedError

    def parse(self, data):
        raise NotImplementedError


class OpenAIProvider(Provider):
    """OpenAI Responses API (POST /v1/responses). 2026-10-31 공식 문서 기준:
    instructions = 시스템 지침, input = 역할별 메시지, max_output_tokens(추론 토큰 포함, 최소 16),
    reasoning.effort(none/low/…), store=false(대화를 OpenAI 쪽에 저장하지 않음).
    답변 글은 output 배열에서 type="message" 항목의 content 중 type="output_text"."""

    name = "openai"
    url = "https://api.openai.com/v1/responses"

    def request(self, *, model, api_key, system, messages, max_output_tokens, reasoning_effort):
        body = {
            "model": model,
            "instructions": system,
            "input": [{"role": m.role, "content": m.content} for m in messages],
            "max_output_tokens": max_output_tokens,
            "store": False,
        }
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        return self.url, headers, body

    def parse(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("output"), list):
            raise LLMError("bad_response")
        texts, refusals = [], []
        for item in data["output"]:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    texts.append(part["text"])
                elif part.get("type") == "refusal" and isinstance(part.get("refusal"), str):
                    refusals.append(part["refusal"])
        text = "\n".join(t for t in texts if t.strip()).strip() or "\n".join(refusals).strip()
        if not text:
            # 출력 한도를 추론에 다 써서 글이 없는 경우 등(status=incomplete)
            raise LLMError("empty")
        return text


PROVIDERS = {p.name: p for p in [OpenAIProvider()]}


def is_enabled():
    return settings.LLM_PROVIDER in PROVIDERS and bool(settings.LLM_API_KEY) and bool(settings.LLM_MODEL)


def _send(url, headers, body, timeout):
    """실제 HTTP 요청. (상태 코드, 응답 바이트). 연결 실패·시간 초과는 LLMError."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read()
        finally:
            exc.close()
    except (TimeoutError, socket.timeout):
        raise LLMError("timeout") from None
    except urllib.error.URLError as exc:
        kind = "timeout" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "network"
        raise LLMError(kind) from None
    except OSError:
        raise LLMError("network") from None


def _error_code(raw):
    """OpenAI 오류 응답에서 짧은 분류 코드만(메시지 본문은 쓰지 않는다)."""
    try:
        err = json.loads(raw.decode("utf-8")).get("error") or {}
        code = err.get("code") or err.get("type") or ""
        return str(code)[:40]
    except (ValueError, AttributeError, UnicodeDecodeError):
        return ""


def complete(system, messages):
    """시스템 지침 + 메시지 → 답변 글. 실패하면 LLMError."""
    if not is_enabled():
        raise LLMError("disabled")
    provider = PROVIDERS[settings.LLM_PROVIDER]
    url, headers, body = provider.request(
        model=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        system=system,
        messages=messages,
        max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        reasoning_effort=settings.LLM_REASONING_EFFORT,
    )
    started = time.monotonic()
    log = {"provider": provider.name, "model": settings.LLM_MODEL}
    try:
        status, raw = _send(url, headers, body, settings.LLM_TIMEOUT_SECONDS)
    except LLMError as exc:
        logger.warning("LLM 호출 실패 %s kind=%s %.1fs", log, exc.kind, time.monotonic() - started)
        raise
    elapsed = time.monotonic() - started
    if status != 200:
        kind = "auth" if status in (401, 403) else "rate_limit" if status == 429 else "http"
        logger.warning("LLM 호출 실패 %s status=%s code=%s %.1fs", log, status, _error_code(raw), elapsed)
        raise LLMError(kind, status)
    try:
        data = json.loads(raw.decode("utf-8"))
        text = provider.parse(data)
    except LLMError as exc:
        logger.warning("LLM 응답 처리 실패 %s kind=%s %.1fs", log, exc.kind, elapsed)
        raise
    except (ValueError, UnicodeDecodeError):
        logger.warning("LLM 응답 처리 실패 %s kind=bad_response %.1fs", log, elapsed)
        raise LLMError("bad_response") from None
    logger.info("LLM 호출 %s status=200 %.1fs", log, elapsed)
    return text
