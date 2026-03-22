import os
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS
from pydantic import ValidationError

from backend.ai.quiz_agent import chat_reply, evaluate_answer, generate_batch_questions, generate_question
from backend.ai.schemas import (
    ChatRequest,
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    GenerateQuestionRequest,
    GenerateBatchQuestionsRequest,
    ChatResponse,
    QuizSessionSaveRequest,
)
from backend.db.mongo_sessions import list_quiz_sessions, save_quiz_session_document


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app)

    @app.get("/")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/generate-question")
    def api_generate_question():
        try:
            payload = request.get_json(force=True)
            req = GenerateQuestionRequest.model_validate(payload)
            question = generate_question(req)
            # Plan contract: return question fields at the response root.
            return jsonify(question.model_dump())
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        except Exception as e:
            return (
                jsonify(
                    {
                        "error": "Failed to generate question",
                        "details": str(e),
                    }
                ),
                500,
            )

    @app.post("/api/generate-batch-questions")
    def api_generate_batch_questions():
        try:
            payload = request.get_json(force=True)
            req = GenerateBatchQuestionsRequest.model_validate(payload)
            questions = generate_batch_questions(req)
            return jsonify({"questions": [q.model_dump() for q in questions]})
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        except Exception as e:
            return jsonify({"error": "Failed to generate batch questions", "details": str(e)}), 500

    @app.post("/api/evaluate-answer")
    def api_evaluate_answer():
        try:
            payload = request.get_json(force=True)
            # Support both:
            # 1) { question: <QuizQuestion>, userAnswer: {selected/text} } (internal shape)
            # 2) Flattened plan shape:
            #    { question: "...", type, options, correctAnswer, userAnswer: [...] | "..." }
            try:
                req = EvaluateAnswerRequest.model_validate(payload)
            except ValidationError:
                qtype = payload.get("type")
                if not qtype:
                    raise

                question_obj = {
                    "question": payload.get("question"),
                    "type": qtype,
                    "options": payload.get("options"),
                    "correctAnswer": payload.get("correctAnswer"),
                    "explanation": payload.get("explanation", ""),
                }

                ua_raw = payload.get("userAnswer")
                if qtype == "text":
                    if isinstance(ua_raw, str):
                        user_answer_obj = {"text": ua_raw}
                    elif isinstance(ua_raw, dict):
                        user_answer_obj = {"text": ua_raw.get("text", "")}
                    else:
                        user_answer_obj = {"text": str(ua_raw or "")}
                else:
                    if isinstance(ua_raw, list):
                        user_answer_obj = {"selected": ua_raw}
                    elif isinstance(ua_raw, dict):
                        user_answer_obj = {"selected": ua_raw.get("selected", [])}
                    else:
                        user_answer_obj = {"selected": [str(ua_raw)] if ua_raw is not None else []}

                req = EvaluateAnswerRequest.model_validate({"question": question_obj, "userAnswer": user_answer_obj})

            result = evaluate_answer(req)
            resp = EvaluateAnswerResponse.model_validate(result)
            return jsonify(resp.model_dump())
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        except Exception as e:
            return (
                jsonify(
                    {
                        "error": "Failed to evaluate answer",
                        "details": str(e),
                    }
                ),
                500,
            )

    @app.post("/api/chat")
    def api_chat():
        try:
            payload = request.get_json(force=True)
            req = ChatRequest.model_validate(payload)
            reply_text = chat_reply(req)
            return jsonify(ChatResponse(reply=reply_text).model_dump())
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        except Exception as e:
            return jsonify({"error": "Failed to generate chat reply", "details": str(e)}), 500

    @app.post("/api/save-quiz-session")
    def api_save_quiz_session():
        """
        Persist an anonymous quiz session (topic, mode, counts, per-question outcome).
        No-op in DB if MONGODB_URI is unset; still returns 200 with saved=false.
        """
        try:
            payload = request.get_json(force=True)
            req = QuizSessionSaveRequest.model_validate(payload)
            doc = {
                "savedAt": datetime.now(timezone.utc),
                "topic": req.topic,
                "difficulty": req.difficulty,
                "questionType": req.questionType,
                "questionCount": req.questionCount,
                "totalScore": req.totalScore,
                "maxScore": req.maxScore,
                "results": req.results,
            }
            saved = save_quiz_session_document(doc)
            return jsonify({"ok": True, "saved": saved})
        except ValidationError as e:
            return jsonify({"error": "Invalid request", "details": e.errors()}), 400
        except Exception as e:
            return jsonify({"error": "Failed to save quiz session", "details": str(e)}), 500

    @app.get("/api/quiz-sessions")
    def api_list_quiz_sessions():
        """Paginated list of saved sessions (newest first). Empty if MongoDB is not configured."""
        try:
            offset = int(request.args.get("offset", 0))
            limit = int(request.args.get("limit", 5))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid offset or limit"}), 400

        offset = max(0, offset)
        limit = max(1, min(limit, 50))

        sessions, total = list_quiz_sessions(offset=offset, limit=limit)
        return jsonify(
            {
                "sessions": sessions,
                "total": total,
                "offset": offset,
                "limit": limit,
            }
        )

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    create_app().run(host="0.0.0.0", port=port, debug=True)

