from dataclasses import dataclass

from app.integrations.ai.schemas import InterpretationAmbiguity
from app.processing.source import SourceBundle
from app.processing.validation import normalize_excerpt


@dataclass(frozen=True)
class VerifiedInterpretationCandidate:
    interpretation: str
    source_id: str
    source_label: str
    excerpt: str


@dataclass(frozen=True)
class VerifiedInterpretationAmbiguity:
    field_name: str
    explanation: str
    candidates: tuple[VerifiedInterpretationCandidate, ...]


def _source_label(source_type: str, attachment_id: int | None) -> str:
    if source_type == "EMAIL":
        return "Email body"
    return f"PDF attachment {attachment_id}" if attachment_id else "PDF attachment"


def verify_interpretation_ambiguities(
    bundle: SourceBundle,
    ambiguities: list[InterpretationAmbiguity] | tuple[InterpretationAmbiguity, ...],
) -> tuple[VerifiedInterpretationAmbiguity, ...]:
    """Accept only bounded ambiguities whose candidate context exists in a real source."""
    verified: list[VerifiedInterpretationAmbiguity] = []
    for ambiguity in ambiguities:
        candidates: list[VerifiedInterpretationCandidate] = []
        interpretations: set[str] = set()
        for candidate in ambiguity.candidates:
            document = bundle.source_map.get(candidate.source_id)
            if document is None or normalize_excerpt(candidate.excerpt) not in normalize_excerpt(
                document.content
            ):
                candidates = []
                break
            interpretation_key = normalize_excerpt(candidate.interpretation)
            if interpretation_key in interpretations:
                continue
            interpretations.add(interpretation_key)
            candidates.append(
                VerifiedInterpretationCandidate(
                    interpretation=candidate.interpretation,
                    source_id=document.source_id,
                    source_label=_source_label(document.source_type, document.attachment_id),
                    excerpt=candidate.excerpt,
                )
            )
        if len(candidates) >= 2:
            verified.append(
                VerifiedInterpretationAmbiguity(
                    field_name=ambiguity.field_name,
                    explanation=ambiguity.explanation,
                    candidates=tuple(candidates),
                )
            )
    return tuple(verified)
