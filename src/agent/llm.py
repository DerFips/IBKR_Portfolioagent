"""Zentrale LLM-Schicht: Ollama (lokal), Claude (Anthropic API) oder NVIDIA NIM.

Alle Module rufen nur `chat()` auf; der Provider wird ueber
LLM_PROVIDER ("ollama" | "anthropic" | "nvidia") in den Einstellungen gewaehlt.
"""
import asyncio
import json
import logging
import time

import httpx

from .settings import Settings

log = logging.getLogger(__name__)

_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class LLMError(RuntimeError):
    pass


def provider_label(s: Settings) -> str:
    if s.llm_provider.lower() == "anthropic":
        return f"Claude ({s.anthropic_model})"
    if s.llm_provider.lower() == "nvidia":
        return f"NVIDIA ({s.nvidia_model})"
    if s.llm_provider.lower() == "hermes":
        return f"Hermes Agent ({s.hermes_model})"
    return f"Ollama ({s.ollama_model})"


async def chat(messages: list, s: Settings, temperature: float = 0.3,
               schema: dict | None = None, max_tokens: int = 4000) -> str:
    """Sendet Chat-Nachrichten ([{role, content}]) und liefert den Antworttext.

    schema: optionales JSON-Schema; bei Claude wird die Antwort damit
    garantiert als valides JSON geliefert (Structured Outputs).
    """
    if s.llm_provider.lower() == "anthropic":
        return await _claude(messages, s, schema, max_tokens)
    if s.llm_provider.lower() == "nvidia":
        return await _nvidia(messages, s, temperature, max_tokens)
    if s.llm_provider.lower() == "hermes":
        return await _hermes(messages, s)
    return await _ollama(messages, s, temperature)


async def _ollama(messages: list, s: Settings, temperature: float) -> str:
    payload = {
        "model": s.ollama_model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(float(s.ollama_timeout), connect=10.0)) as client:
        resp = await client.post(f"{s.ollama_base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _stream_chat(url: str, headers: dict, payload: dict, name: str,
                       total_timeout: float, idle_timeout: float) -> str:
    """OpenAI-kompatible Chat-Completion per SSE-Stream lesen.

    Streaming statt Warten auf die komplette Antwort: das Lese-Timeout gilt nur fuer
    Pausen zwischen Chunks (idle), nicht fuer die Gesamtdauer – lange Antworten
    laufen so durch, haengende Verbindungen werden trotzdem erkannt.
    Rueckgabe: zusammengesetzter Antworttext. Wirft LLMError mit klarer Ursache.
    """
    timeout = httpx.Timeout(connect=10.0, read=idle_timeout, write=30.0, pool=30.0)
    parts: list[str] = []
    reasoned = 0
    finish = None
    try:
        async with asyncio.timeout(total_timeout):
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, headers=headers,
                                         json={**payload, "stream": True}) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode("utf-8", "replace")[:200]
                        _raise_status(name, r.status_code, body, payload.get("model", ""))
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue          # Keepalive-Kommentare (":") und event:-Zeilen
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            ch = json.loads(data)["choices"][0]
                        except (ValueError, KeyError, IndexError):
                            continue          # z.B. Tool-Progress-Events von Hermes
                        delta = ch.get("delta") or {}
                        parts.append(delta.get("content") or "")
                        # Reasoning-Modelle senden erst "reasoning(_content)", dann "content"
                        reasoned += len(delta.get("reasoning_content") or delta.get("reasoning") or "")
                        finish = ch.get("finish_reason") or finish
    except TimeoutError as e:
        raise LLMError(f"{name}: Gesamtzeit von {int(total_timeout)} s ueberschritten "
                       f"(Timeout in den Einstellungen erhoehen)") from e
    except httpx.ReadTimeout as e:
        raise LLMError(f"{name}: seit {int(idle_timeout)} s keine Daten mehr empfangen "
                       f"(Modell haengt/ueberlastet oder fuer dein Konto nicht nutzbar – "
                       f"anderes Modell waehlen)") from e
    except httpx.ConnectError as e:
        raise LLMError(f"{name} nicht erreichbar unter {url}") from e
    except httpx.HTTPError as e:
        raise LLMError(f"{name}-Anfrage fehlgeschlagen ({type(e).__name__}: {e})") from e
    if finish == "error":
        raise LLMError(f"{name} meldet einen Fehler beim Ausfuehren")
    text = "".join(parts)
    if not text.strip() and reasoned:
        raise LLMError(f"{name}: Modell hat das Token-Limit mit Nachdenken verbraucht, bevor "
                       f"die Antwort begann (finish_reason={finish}) – anderes Modell waehlen")
    return text


def _raise_status(name: str, code: int, body: str, model: str) -> None:
    if code in (401, 403):
        raise LLMError(f"{name}: API-Key ungueltig oder ohne Berechtigung")
    if code == 404:
        raise LLMError(f"{name}: Modell '{model}' fuer dein Konto nicht verfuegbar (404) – "
                       f"anderes Modell waehlen")
    if code == 410:
        raise LLMError(f"{name}: Modell '{model}' wurde abgeschaltet (410) – anderes Modell waehlen")
    if code == 429:
        raise LLMError(f"{name}: Rate-Limit bzw. ausgelastet (429)")
    raise LLMError(f"{name}-Fehler {code}: {body}")


async def _nvidia(messages: list, s: Settings, temperature: float, max_tokens: int) -> str:
    """NVIDIA NIM (build.nvidia.com): OpenAI-kompatible Chat-Completions-API."""
    if not s.nvidia_api_key:
        raise LLMError("Kein NVIDIA API-Key hinterlegt (Einstellungen > KI-Modell)")
    payload = {"model": s.nvidia_model, "messages": messages,
               "temperature": temperature,
               # Reasoning-Modelle zaehlen ihr Nachdenken mit: genug Platz fuer die Antwort
               "max_tokens": min(max(max_tokens, 2048), 8192)}
    headers = {"Authorization": f"Bearer {s.nvidia_api_key}", "Accept": "text/event-stream"}
    url = f"{s.nvidia_base_url.rstrip('/')}/chat/completions"
    last = None
    for attempt in range(3):        # nur bei 429/5xx wiederholen, nie bei Timeouts
        try:
            return await _stream_chat(url, headers, payload, "NVIDIA",
                                      float(s.nvidia_timeout), 120.0)
        except LLMError as e:
            last = e
            msg = str(e)
            retryable = "429" in msg or any(f"Fehler {c}" in msg for c in (500, 502, 503, 504))
            if not retryable or attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt * 2)
    raise last


async def _hermes(messages: list, s: Settings) -> str:
    """Hermes Agent (Nous Research) ueber seinen OpenAI-kompatiblen API-Server.

    Hermes ist ein Agent: er recherchiert mit seinen eigenen Tools (Web etc.) und
    antwortet erst am Ende. Per Stream sendet er waehrenddessen Keepalives.
    """
    if not s.hermes_api_key:
        raise LLMError("Kein Hermes API_SERVER_KEY hinterlegt (Einstellungen > KI-Modell)")
    headers = {"Authorization": f"Bearer {s.hermes_api_key}", "Accept": "text/event-stream"}
    url = f"{s.hermes_base_url.rstrip('/')}/chat/completions"
    try:
        text = await _stream_chat(url, headers,
                                  {"model": s.hermes_model, "messages": messages},
                                  "Hermes", float(s.hermes_timeout), 180.0)
        # Hermes meldet eigene Fehler (z.B. fehlender Provider-Login) als normalen Antworttext
        if text.lstrip().startswith("⚠") and len(text) < 600:
            raise LLMError(f"Hermes meldet: {' '.join(text.split())}")
        return text
    except LLMError as e:
        if "Dashboard requests" in str(e) or "Invalid Host header" in str(e):
            raise LLMError("Hermes: Das ist das Hermes-DASHBOARD (Port 9119), nicht der API-Server. "
                           "HERMES_BASE_URL auf http://host.docker.internal:8642/v1 setzen.") from e
        if "nicht erreichbar" in str(e):
            raise LLMError(f"{e} – laeuft 'hermes gateway' mit API_SERVER_ENABLED=true? "
                           f"(Hermes standardmaessig nur auf 127.0.0.1:8642)") from e
        raise


async def _claude(messages: list, s: Settings, schema: dict | None,
                  max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("Paket 'anthropic' fehlt (pip install anthropic)") from e
    if not s.anthropic_api_key:
        raise LLMError("Kein Anthropic API-Key hinterlegt (Einstellungen > KI-Modell)")

    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    convo = [m for m in messages if m["role"] != "system"]

    output_config: dict = {}
    if s.anthropic_effort in _EFFORTS:
        output_config["effort"] = s.anthropic_effort
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    kwargs: dict = dict(model=s.anthropic_model, max_tokens=max_tokens, messages=convo)
    if system:
        kwargs["system"] = system
    if output_config:
        kwargs["output_config"] = output_config

    client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key,
                                      timeout=120.0, max_retries=3)
    try:
        resp = await client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API-Key ungueltig") from e
    except anthropic.PermissionDeniedError as e:
        raise LLMError("Anthropic API-Key hat keine Berechtigung fuer dieses Modell") from e
    except anthropic.NotFoundError as e:
        raise LLMError(f"Modell '{s.anthropic_model}' nicht gefunden") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Anthropic Rate-Limit erreicht") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anfrage abgelehnt: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Keine Verbindung zur Anthropic API") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API-Fehler {e.status_code}: {e.message}") from e

    if resp.stop_reason == "refusal":
        raise LLMError("Claude hat die Anfrage abgelehnt")
    u = resp.usage
    log.debug(f"[claude] in={u.input_tokens} out={u.output_tokens} stop={resp.stop_reason}")
    text = next((b.text for b in resp.content if b.type == "text"), "")
    if not text:
        raise LLMError(f"Leere Antwort (stop_reason={resp.stop_reason})")
    return text


async def research(system: str, user: str, s: Settings, max_searches: int = 10,
                   max_tokens: int = 32000) -> tuple[str, list[dict], bool]:
    """Recherche mit Live-Websuche (nur Claude). Liefert (text, quellen, live).

    Bei Ollama gibt es keine Websuche: das Modell antwortet aus seinem Trainingswissen
    (live=False) – der Aufrufer muss das dem Nutzer deutlich sagen.
    """
    if s.llm_provider.lower() != "anthropic":
        text = await chat([{"role": "system", "content": system},
                           {"role": "user", "content": user}], s, 0.2, max_tokens=8000)
        return text, [], False

    try:
        import anthropic
    except ImportError as e:
        raise LLMError("Paket 'anthropic' fehlt (pip install anthropic)") from e
    if not s.anthropic_api_key:
        raise LLMError("Kein Anthropic API-Key hinterlegt (Einstellungen > KI-Modell)")

    # Haiku kennt nur die Basis-Variante der Websuche
    tool_type = "web_search_20250305" if "haiku" in s.anthropic_model else "web_search_20260209"
    kwargs: dict = dict(
        model=s.anthropic_model, max_tokens=max_tokens, system=system,
        tools=[{"type": tool_type, "name": "web_search", "max_uses": max_searches}],
    )
    if s.anthropic_effort in _EFFORTS:
        kwargs["output_config"] = {"effort": s.anthropic_effort}

    messages = [{"role": "user", "content": user}]
    sources: dict[str, str] = {}
    client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key, timeout=600.0, max_retries=2)
    msg = None
    try:
        for _ in range(6):      # pause_turn: lange Server-Tool-Turns fortsetzen
            async with client.messages.stream(messages=messages, **kwargs) as stream:
                msg = await stream.get_final_message()
            for b in msg.content:
                if b.type == "web_search_tool_result" and isinstance(b.content, list):
                    for r in b.content:
                        url = getattr(r, "url", "")
                        if url:
                            sources.setdefault(url, getattr(r, "title", "") or url)
            if msg.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": msg.content}]
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API-Key ungueltig") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Anthropic Rate-Limit erreicht") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anfrage abgelehnt: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Keine Verbindung zur Anthropic API") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API-Fehler {e.status_code}: {e.message}") from e

    if msg is None or msg.stop_reason == "refusal":
        raise LLMError("Claude hat die Anfrage abgelehnt")
    text = "".join(b.text for b in msg.content if b.type == "text")
    if not text.strip():
        raise LLMError(f"Leere Antwort (stop_reason={msg.stop_reason})")
    return text, [{"url": u, "title": ti} for u, ti in sources.items()], True


async def test_connection(s: Settings) -> dict:
    """Kleiner Ping fuer den 'Verbindung testen'-Button."""
    t0 = time.monotonic()
    try:
        out = await chat(
            [{"role": "user", "content": "Antworte nur mit dem Wort: OK"}],
            s, temperature=0.0, max_tokens=1000,
        )
        return {"ok": True, "provider": provider_label(s),
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "reply": out.strip()[:80]}
    except Exception as e:
        return {"ok": False, "provider": provider_label(s), "error": str(e) or type(e).__name__}
