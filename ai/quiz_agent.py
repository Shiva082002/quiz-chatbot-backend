from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from google import genai
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

from .schemas import (
    Difficulty,
    ChatRequest,
    EvaluateAnswerRequest,
    GenerateBatchQuestionsRequest,
    GenerateQuestionRequest,
    QuestionType,
    QuizQuestion,
)


class _LlmEvaluation(BaseModel):
    isCorrect: bool
    correctAnswer: list[str]
    explanation: str


def _extract_json(candidate: str) -> str:
    """
    Gemini sometimes wraps JSON in markdown/code fences or adds leading/trailing text.
    This extracts the most likely JSON object substring.
    """
    if "```" in candidate:
        # Try to extract the first fenced JSON block.
        start = candidate.find("```")
        # Find first { after the first fence marker.
        obj_start = candidate.find("{", start)
        obj_end = candidate.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            return candidate[obj_start : obj_end + 1]

    obj_start = candidate.find("{")
    obj_end = candidate.rfind("}")
    if obj_start == -1 or obj_end == -1 or obj_end <= obj_start:
        raise ValueError("Could not locate JSON object in model output.")
    return candidate[obj_start : obj_end + 1]


def _get_model() -> Any:
    # Allows local development with a `.env` file (ignored in production env var setups).
    # We explicitly load `backend/.env` so it works even if you run Flask from repo root.
    backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_dotenv(dotenv_path=os.path.join(backend_dir, ".env"), override=False)

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Missing API key. Set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in `backend/.env`."
        )

    # Default chosen to align with your snippet/model.
    model_name = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    client = genai.Client(api_key=api_key)
    return client, model_name


def _call_model_text(prompt: str) -> str:
    client, model_name = _get_model()
    resp = client.models.generate_content(
        model=model_name,
        contents=prompt,
    )
    return getattr(resp, "text", None) or str(resp)


def _extract_json_array(candidate: str) -> str:
    """
    Extract JSON array substring from model output.
    Supports both raw JSON and fenced outputs.
    """
    if "```" in candidate:
        # If fenced, keep the entire string but still locate '[' ... ']'.
        # (Most models only include one JSON block anyway.)
        pass

    arr_start = candidate.find("[")
    arr_end = candidate.rfind("]")
    if arr_start == -1 or arr_end == -1 or arr_end <= arr_start:
        raise ValueError("Could not locate JSON array in model output.")
    return candidate[arr_start : arr_end + 1]


def generate_question(
    req: GenerateQuestionRequest,
    *,
    max_attempts: int = 3,
) -> QuizQuestion:
    """
    Generates a single quiz question as strict JSON.
    """
    prompt = f"""
You are a Quiz Master.
Generate a question in strict JSON format.

Rules:
- Output ONLY valid JSON (no markdown, no commentary).
- Include: question, type, options (if applicable), correctAnswer, explanation
- Always include exactly 4 options for MCQ.
- Use only these types: "single", "multi", "text"
- Keep answers concise.
- Do not repeat questions from history.
- It must be relevant to the given topic and difficulty.

Input:
- topic: {req.topic}
- difficulty: {req.difficulty}
- type: {req.type}
- history: {req.history}

Output schema:
{{
  "question": string,
  "type": "single" | "multi" | "text",
  "options": string[] | null,
  "correctAnswer": string[],
  "explanation": string
}}

Type rules:
- For "single": options is a 4-item string array; correctAnswer is a 1-item array containing exactly one option.
- For "multi": options is a 4-item string array; correctAnswer is a non-empty subset of options.
- For "text": options must be null; correctAnswer is a 1-item array with an expected short answer phrase.
"""

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_model_text(prompt)
            json_str = _extract_json(raw)
            data = json.loads(json_str)
            # Validate/normalize structure.
            return QuizQuestion.model_validate(data)
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            raise RuntimeError(f"Failed to generate valid JSON question after {max_attempts} attempts: {e}") from e

    raise RuntimeError(f"Failed to generate question: {last_err}")


def generate_batch_questions(
    req: GenerateBatchQuestionsRequest,
    *,
    max_attempts: int = 3,
) -> list[QuizQuestion]:
    """
    Generates multiple quiz questions in a single AI call.
    This reduces quota usage: one call per batch (e.g. 5 questions).
    """
    prompt = f"""
You are a Quiz Master.
Generate exactly {req.count} quiz questions in strict JSON array format.

Rules:
- Output ONLY valid JSON (no markdown, no commentary).
- Each array item must include: question, type, options (if applicable), correctAnswer, explanation
- Use only these types: "single", "multi", "text" (must be "{req.type}" for every item)
- Always include exactly 4 options for MCQ types ("single" and "multi").
- Keep answers concise.
- Do not repeat questions across the provided history.
- Make them relevant to the given topic and difficulty.

Input:
- topic: {req.topic}
- difficulty: {req.difficulty}
- type: {req.type}
- history: {req.history}

Output schema (JSON array):
[
  {{
    "question": string,
    "type": "{req.type}",
    "options": string[] | null,
    "correctAnswer": string[],
    "explanation": string
  }}
]

Type rules:
- For "single": options is a 4-item string array; correctAnswer is a 1-item array with exactly one option.
- For "multi": options is a 4-item string array; correctAnswer is a non-empty subset of options.
- For "text": options must be null; correctAnswer is a 1-item array with an expected short answer phrase.
"""

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_model_text(prompt)
            json_str = _extract_json_array(raw)
            data = json.loads(json_str)
            if not isinstance(data, list) or len(data) != req.count:
                raise ValueError(f"Expected JSON array with length {req.count}, got {len(data) if isinstance(data, list) else 'non-list'}.")

            questions = [QuizQuestion.model_validate(item) for item in data]

            # Sanity: ensure all question types match requested type.
            if any(q.type != req.type for q in questions):
                raise ValueError("Model returned a question with an unexpected type.")

            return questions
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            raise RuntimeError(f"Failed to generate valid JSON batch after {max_attempts} attempts: {e}") from e

    raise RuntimeError(f"Failed to generate batch questions: {last_err}")


def evaluate_answer(
    req: EvaluateAnswerRequest,
    *,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """
    Evaluates the user's answer and returns:
    status: correct|partial|incorrect
    isCorrect: boolean
    scoreAwarded: 0..1
    correctAnswer: string[]
    explanation: string
    """
    q: QuizQuestion = req.question
    qtype: QuestionType = q.type
    correct_answer = q.correctAnswer

    # Deterministic scoring for single/multi (supports partial credit for multi).
    if qtype == "single":
        selected = req.userAnswer.selected or []
        expected = correct_answer[0]
        is_correct = selected == [expected]
        score = 1.0 if is_correct else 0.0
        status = "correct" if is_correct else "incorrect"
    elif qtype == "multi":
        selected = set(req.userAnswer.selected or [])
        correct_set = set(correct_answer)
        if not (selected or correct_set):
            score = 0.0
            status = "incorrect"
            is_correct = False
        else:
            intersection = len(selected.intersection(correct_set))
            union = len(selected.union(correct_set))
            score = (intersection / union) if union else 0.0
            status = "correct" if score == 1.0 else ("partial" if score > 0 else "incorrect")
            is_correct = status == "correct"
    else:
        # For text, LLM decides correctness (with close matches).
        is_correct = False
        score = 0.0
        status = "incorrect"

    explanation: str = "Explanation not available."

    # Ask Gemini for explanation (and correctness for text).
    prompt = f"""
You are evaluating a quiz answer.
Output ONLY valid JSON (no markdown, no commentary).

Rules:
- Be strict but fair.
- For text answers, allow close matches.
- Output ONLY JSON with keys: isCorrect, correctAnswer, explanation

Input:
- question: {q.model_dump()}
- userAnswer: {req.userAnswer.model_dump()}
"""

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_model_text(prompt)
            json_str = _extract_json(raw)
            data = json.loads(json_str)
            llm_eval = _LlmEvaluation.model_validate(data)
            # Prefer explanation from model.
            explanation = llm_eval.explanation.strip()

            if qtype == "text":
                is_correct = bool(llm_eval.isCorrect)
                score = 1.0 if is_correct else 0.0
                status = "correct" if is_correct else "incorrect"

            break
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            # Fallback explanation for evaluation failures.
            explanation = (
                "Could not reliably parse the model explanation; "
                "here is the correct answer."
            )
            break

    return {
        "status": status,
        "isCorrect": is_correct,
        "scoreAwarded": float(score),
        "correctAnswer": list(correct_answer),
        "explanation": explanation,
    }


def chat_reply(
    req: ChatRequest,
    *,
    max_attempts: int = 2,
) -> str:
    """
    General chat about the given topic (non-quiz).
    Returns plain text (no strict JSON).
    """
    prompt = f"""
You are a helpful tutor and explainer.
Topic: {req.topic}

Conversation history:
"""

    # Include history in a simple readable format.
    for m in req.history[-20:]:
        role = "User" if m.role == "user" else "Assistant"
        prompt += f"\n{role}: {m.content}"

    prompt += f"\nUser: {req.message}\nAssistant:"

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw = _call_model_text(prompt)
            # Gemini may include extra whitespace; keep the main text.
            return (raw or '').strip()
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                time.sleep(0.5 * attempt)
                continue
            raise RuntimeError(f"Failed to generate chat reply: {e}") from e

    raise RuntimeError(f"Failed to generate chat reply: {last_err}")

