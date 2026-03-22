from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


Difficulty = Literal["easy", "medium", "hard"]
QuestionType = Literal["single", "multi", "text"]
Status = Literal["correct", "partial", "incorrect"]


class GenerateQuestionRequest(BaseModel):
    topic: str
    difficulty: Difficulty
    type: QuestionType
    history: list[str] = Field(default_factory=list)


class GenerateBatchQuestionsRequest(BaseModel):
    topic: str
    difficulty: Difficulty
    type: QuestionType
    count: int = Field(ge=1, le=10)
    history: list[str] = Field(default_factory=list)


class QuizQuestion(BaseModel):
    question: str
    type: QuestionType
    options: Optional[list[str]] = None
    correctAnswer: list[str]
    # During evaluation requests the frontend may not include the original explanation,
    # but we still keep the schema compatible with generation responses.
    explanation: str = ''

    @model_validator(mode="after")
    def validate_by_type(self) -> "QuizQuestion":
        qtype = self.type

        if qtype in ("single", "multi"):
            if not self.options or len(self.options) != 4:
                raise ValueError("For single/multi, options must contain exactly 4 items.")
            if not self.correctAnswer:
                raise ValueError("correctAnswer must not be empty.")
            if any(o not in self.options for o in self.correctAnswer):
                raise ValueError("correctAnswer items must be present in options.")

        if qtype == "single":
            if len(self.correctAnswer) != 1:
                raise ValueError("For single, correctAnswer must contain exactly 1 item.")

        if qtype == "text":
            # For text questions we do not require options.
            if self.options is not None:
                raise ValueError("For text, options must be null.")
            if len(self.correctAnswer) != 1:
                raise ValueError("For text, correctAnswer must contain exactly 1 item.")

        return self


class EvaluateUserAnswer(BaseModel):
    selected: Optional[list[str]] = None
    text: Optional[str] = None


class EvaluateAnswerRequest(BaseModel):
    question: QuizQuestion
    userAnswer: EvaluateUserAnswer

    @model_validator(mode="after")
    def validate_by_type(self) -> "EvaluateAnswerRequest":
        qtype = self.question.type

        if qtype in ("single", "multi"):
            if self.userAnswer.selected is None:
                raise ValueError("For single/multi, userAnswer.selected must be provided.")
            # Ensure selected values are from the options; frontend should enforce, but we validate.
            if any(sel not in self.question.options for sel in self.userAnswer.selected or []):
                raise ValueError("userAnswer.selected must be present in question.options.")
        else:
            # qtype == "text"
            if self.userAnswer.text is None:
                raise ValueError("For text, userAnswer.text must be provided.")

        return self


class GenerateQuestionResponse(BaseModel):
    question: QuizQuestion


class EvaluateAnswerResponse(BaseModel):
    status: Status
    isCorrect: bool
    scoreAwarded: float = Field(ge=0.0, le=1.0)
    correctAnswer: list[str]
    explanation: str


class GenerateBatchQuestionsResponse(BaseModel):
    questions: list[QuizQuestion]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    topic: str
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str


class QuizSessionSaveRequest(BaseModel):
    """Anonymous quiz result payload from the frontend (stored in MongoDB)."""

    topic: str
    difficulty: Difficulty
    questionType: QuestionType
    questionCount: int = Field(ge=1, le=200)
    totalScore: Optional[float] = None
    maxScore: Optional[float] = None
    results: list[dict[str, Any]] = Field(default_factory=list)

