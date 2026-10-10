import json
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

# NVIDIA NIM provides an OpenAI-compatible chat-completions endpoint.
# See: https://integrate.api.nvidia.com/v1/chat/completions
API_BASE = os.getenv("NVIDIA_API_BASE", "https://integrate.api.nvidia.com/v1/chat/completions")
API_ROOT = API_BASE.rsplit("/chat/completions", 1)[0]
API_KEY = os.getenv("NVIDIA_API_KEY", "")
MODEL = os.getenv("STUDYAI_GEN_MODEL", "stepfun-ai/step-3.7-flash")
FALLBACK_MODELS = [m.strip() for m in os.getenv("STUDYAI_FALLBACK_MODELS", "openai/gpt-oss-20b,meta/llama-3.3-70b-instruct").split(",") if m.strip()]
TIMEOUT = int(os.getenv("STUDYAI_AI_TIMEOUT_SECONDS", "45"))
MAX_RETRIES = int(os.getenv("STUDYAI_AI_RETRIES", "0"))

BUDGET = int(os.getenv("STUDYAI_AI_BUDGET_SECONDS", "52"))  # total wall time per request (serverless limit)


class LLMError(RuntimeError):
    pass


def _join(parts, marker=""):
    sep = "\n\n" + (marker + "\n\n" if marker else "")
    return sep.join(parts)


def _friendly_http_error(status, body):
    body_l = (body or "").lower()
    if status == 410 and ("public api" in body_l or "endpoint" in body_l or "gone" in body_l):
        return (
            "NVIDIA API authentication is working, but inference access is not enabled for this NVIDIA organization/API key "
            "(HTTP 410). The /v1/models endpoint may still work while /v1/chat/completions is blocked. "
            "Enable Public API Endpoints/hosted inference for the organization in NVIDIA Build, then create a new API key, "
            "put it in .env, and restart StudyAI. This cannot be fixed by changing the model in the application."
        )

    if status == 401:
        return "NVIDIA API authentication failed. Check NVIDIA_API_KEY in your .env file."
    if status == 403:
        return "NVIDIA API access was denied. Check your NVIDIA API key and account access."
    if status == 404:
        return "The configured NVIDIA model was not found or is not available to this API key."
    if status == 410:
        return ("NVIDIA rejected the selected public inference endpoint (HTTP 410). "
                "StudyAI tried its fallback models. If all models return 410, enable 'Public API Endpoints' "
                "for your NVIDIA organization/API key in NVIDIA Build, then restart StudyAI.")
    if status == 429:
        return "The NVIDIA AI service is temporarily rate-limited. Please wait a moment and try again."
    if 500 <= status <= 599:
        return "The NVIDIA AI service is temporarily unavailable. Please try again in a moment."
    return f"NVIDIA AI request failed (HTTP {status}). Please try again."


def _schema_instruction(schema):
    if not schema:
        return ""
    return (
        "\n\nOUTPUT FORMAT REQUIREMENT:\n"
        "Return ONLY valid JSON. Do not use Markdown fences, commentary, or extra text. "
        "The JSON must follow this schema:\n"
        + json.dumps(schema, separators=(",", ":"))
    )


def check_nvidia_access():
    """Return a diagnostic dict without making an inference request."""
    if not API_KEY:
        return {"configured": False, "models_http": None, "inference": "not_tested",
                "message": "NVIDIA_API_KEY is not configured."}
    try:
        r = requests.get(
            API_ROOT + "/models",
            headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"},
            timeout=min(TIMEOUT, 20),
        )
        if r.status_code == 200:
            try:
                data = r.json()
                ids = [x.get("id") for x in (data.get("data") or []) if isinstance(x, dict)]
            except Exception:
                ids = []
            return {"configured": True, "models_http": 200, "inference": "not_tested",
                    "models_count": len(ids), "message": "API key is valid and /v1/models is reachable. Inference permission must still be checked with a chat request."}
        return {"configured": True, "models_http": r.status_code, "inference": "not_tested",
                "message": _friendly_http_error(r.status_code, r.text)}
    except requests.RequestException:
        return {"configured": True, "models_http": None, "inference": "not_tested",
                "message": "NVIDIA /v1/models could not be reached. Check internet access."}


def _call(system, user, max_tokens=3000, json_schema=None, temperature=0.2):
    if not API_KEY:
        raise LLMError("NVIDIA_API_KEY is not configured. Add your NVIDIA API key to .env and restart StudyAI.")

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user + _schema_instruction(json_schema)},
    ]

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Try the configured model first, then current NVIDIA hosted/free-compatible fallbacks.
    models = []
    for model in [MODEL] + FALLBACK_MODELS:
        if model and model not in models:
            models.append(model)

    last_error = None
    deadline = time.monotonic() + BUDGET
    for model in models:
        if time.monotonic() >= deadline:
            raise LLMError("The AI service took too long to respond. Please try again.")
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # Reasoning models can spend substantial time thinking before returning text.
        # Keep reasoning low for StudyAI's interactive student workflows.
        if model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = requests.post(
                    API_BASE,
                    headers=headers,
                    json=payload,
                    timeout=max(5, min(TIMEOUT, deadline - time.monotonic())),
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    time.sleep(1.5 * (2 ** attempt))
                    continue
                # A network failure is not model-specific; stop rather than hammering fallbacks.
                raise LLMError("The NVIDIA AI service could not be reached. Check your internet connection and NVIDIA API key.") from exc

            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise LLMError("NVIDIA AI returned an invalid response.") from exc

                choices = data.get("choices") or []
                if not choices:
                    last_error = "empty choices"
                    break

                message = choices[0].get("message") or {}
                text = message.get("content") or ""
                if text:
                    return text.strip()
                last_error = "empty answer"
                break

            # NVIDIA HTTP 410 is currently commonly an account/organization provisioning issue, not a model issue.
            # Do not burn requests trying several models when the hosted inference endpoint itself is unavailable.
            if response.status_code == 410:
                raise LLMError(_friendly_http_error(410, response.text))

            # Retry transient rate-limit/server failures.
            if response.status_code == 429 or 500 <= response.status_code <= 599:
                last_error = response.text[:800]
                if attempt < MAX_RETRIES:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else 1.0 * (2 ** attempt)
                    except ValueError:
                        delay = 1.0 * (2 ** attempt)
                    time.sleep(min(delay, 6))
                    continue
                # Move to the next model immediately after a transient failure.
                break

            # Other errors are not likely to improve by switching models.
            raise LLMError(_friendly_http_error(response.status_code, response.text))

    raise LLMError("NVIDIA AI could not produce a response. Please try again.")


def _clean_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()

    # Recover from a model adding a short sentence around otherwise-valid JSON.
    starts = [p for p in (text.find("["), text.find("{")) if p >= 0]
    if starts:
        start = min(starts)
        if start > 0:
            text = text[start:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last attempt: trim after the final JSON bracket.
        end = max(text.rfind("]"), text.rfind("}"))
        if end >= 0:
            return json.loads(text[: end + 1])
        raise LLMError("NVIDIA AI returned data in an unexpected format. Please try again.")


def tutor(question, context, history, profile, mode):
    style = {
        "normal": "Give a complete, well-structured college-level explanation.",
        "simple": "Explain from beginner level using simple words, an analogy and an example.",
        "exam": "Give an exam-ready answer with definition, explanation, key points, example and conclusion.",
        "detailed": "Give a thorough explanation with headings, steps, examples, common mistakes and a short recap.",
        "compare": "If comparing concepts, use a clear table followed by explanation; otherwise answer normally and mention useful differences.",
    }.get(mode, "Give a complete explanation.")
    system = f"""You are StudyAI, a professional personalized academic tutor.
{style}
Never intentionally restrict the answer to two lines. Match the student's requested depth.
Use the supplied material as the primary source when available. Do not invent claims that contradict it.
If the material is insufficient, explicitly say what is missing and then, when the question is general academic knowledge,
provide a clearly labelled general explanation.
Student preferences: language={profile.get('preferred_language')}, explanation={profile.get('explanation_style')}, course={profile.get('course')}.
Weak topics should receive extra clarity.
Use Markdown headings, bullets, numbered steps and examples where useful."""
    ctx = "\n\n---SOURCE---\n".join(context) if context else "(No matching document context.)"
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-8:])
    return _call(
        system,
        f"SOURCE MATERIAL:\n{ctx}\n\nRECENT CHAT:\n{hist or '(none)'}\n\nSTUDENT QUESTION:\n{question}",
        max_tokens=3500,
    )


def notes(context, request, profile):
    system = """Create high-quality study notes from the supplied material.
Return Markdown with a title, introduction, clear headings, definitions, detailed explanations,
examples where supported, key points, important exam points and a quick revision section.
Stay grounded in the source. If the user asks a question, answer it in note format."""
    return _call(
        system,
        f"Material:\n{_join(context, '---')}\n\nStudent request: {request}\nStudent style: {profile.get('explanation_style')}",
        max_tokens=3200,
    )


def flashcards(context, count=10):
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "answer": {"type": "string"},
                "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
            },
            "required": ["question", "answer", "difficulty"],
        },
    }
    raw = _call(
        "Create concise study flashcards strictly from the source material.",
        f"Create exactly {count} cards when possible.\nSource:\n{_join(context)}",
        max_tokens=2200,
        json_schema=schema,
    )
    return _clean_json(raw)


def quiz(context, count, difficulty):
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 4},
                "correct_index": {"type": "integer", "minimum": 0, "maximum": 3},
                "explanation": {"type": "string"},
                "topic": {"type": "string"},
            },
            "required": ["question", "options", "correct_index", "explanation", "topic"],
        },
    }
    system = """Create a multiple-choice practice quiz strictly grounded in the source.
Every question MUST have exactly four distinct options. Exactly one option must be correct.
The explanation must justify the correct answer from the source. Avoid ambiguous questions."""
    raw = _call(
        system,
        f"Difficulty: {difficulty}\nNumber: {count}\nSOURCE:\n{_join(context)}",
        max_tokens=2600,
        json_schema=schema,
    )
    return _clean_json(raw)


def planner(context, days, start_date, minutes, profile):
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "day": {"type": "integer"},
                "date": {"type": "string"},
                "title": {"type": "string"},
                "minutes": {"type": "integer"},
                "tasks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["day", "date", "title", "minutes", "tasks"],
        },
    }
    system = """Create a realistic day-by-day study plan. Distribute source topics across the requested days.
Include learning, AI explanation, practice and revision. Do not create dates outside the requested range."""
    raw = _call(
        system,
        f"Start date: {start_date}\nDays: {days}\nDaily minutes: {minutes}\nCourse: {profile.get('course')}\nMaterial:\n{_join(context)}",
        max_tokens=2800,
        json_schema=schema,
    )
    return _clean_json(raw)


def coach(profile, dashboard, topics):
    system = """You are an AI study coach. Give a concise but useful personalized recommendation.
Prioritize weak topics, upcoming exams, consistency and available time. Return Markdown."""
    return _call(
        system,
        f"Profile: {dict(profile or {})}\nDashboard: {dashboard}\nTopic performance: {list(topics)}\nRecommend today's study session and explain why.",
        max_tokens=1200,
    )
