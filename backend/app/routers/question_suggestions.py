"""Contract section 3: POST /api/question-suggestions — host AI assist for the questionnaire."""

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.auth.deps import CurrentUser
from app.services import agents_client

router = APIRouter(prefix="/api", tags=["question-suggestions"])

Text200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text1000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
QuestionKind = Literal["text", "single_choice", "multi_choice", "number"]


class ExistingQuestionIn(BaseModel):
    text: Text1000
    kind: QuestionKind
    options: list[Text200] | None = Field(default=None, max_length=50)
    required: bool = False

    @model_validator(mode="after")
    def _options_match_kind(self):
        if self.kind in ("single_choice", "multi_choice"):
            if not self.options:
                raise ValueError(f"{self.kind} questions need options")
            if len(set(self.options)) != len(self.options):
                raise ValueError("question options must be unique")
        elif self.options is not None:
            raise ValueError(f"{self.kind} questions take no options")
        return self


class QuestionSuggestionsBody(BaseModel):
    name: Text200
    type: Literal["structured", "informal"]
    tone: Literal["professional", "casual"]
    description: str = Field(default="", max_length=5000)
    existing_questions: list[ExistingQuestionIn] = Field(default_factory=list, max_length=30)
    count: int = Field(default=3, ge=1, le=10)
    hint: str | None = Field(default=None, max_length=1000)


def _normalize_question(raw: dict) -> dict | None:
    """Keep only contract-shaped questions from the agents response; drop junk."""
    text = raw.get("text")
    kind = raw.get("kind")
    if not isinstance(text, str) or not text.strip():
        return None
    if kind not in ("text", "single_choice", "multi_choice", "number"):
        return None
    options = raw.get("options")
    if kind in ("single_choice", "multi_choice"):
        if not isinstance(options, list) or not options:
            return None
        options = [str(o) for o in options]
    else:
        options = None
    required = bool(raw.get("required", False))
    return {"text": text.strip(), "kind": kind, "options": options, "required": required}


@router.post("/question-suggestions")
def question_suggestions(body: QuestionSuggestionsBody, user: CurrentUser):
    """Proxy to agents POST /generate-questions. Session auth; does not create an event."""
    del user  # auth only
    agents_body = {
        "event": {
            "name": body.name,
            "type": body.type,
            "tone": body.tone,
            "description": body.description.strip(),
        },
        "existing_questions": [
            {
                "text": q.text,
                "kind": q.kind,
                "options": q.options,
                "required": q.required,
            }
            for q in body.existing_questions
        ],
        "count": body.count,
        "hint": body.hint,
    }
    raw = agents_client.generate_questions(agents_body)
    questions = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_question(item)
        if normalized is not None:
            questions.append(normalized)
    return {"questions": questions}
