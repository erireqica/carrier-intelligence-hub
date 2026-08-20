from dataclasses import asdict

from fastapi import APIRouter

from app.api.dependencies import CsrfUser, CurrentUser, DbSession
from app.api.schemas.domain import (
    MessageAnalysisResponse,
    MessageProcessingResult,
    ReviewDetailResponse,
    ReviewDismissRequest,
)
from app.integrations.ai.schemas import HumanAnalysisInput
from app.services import message_processing, operations

router = APIRouter(tags=["processing"])


def response_from_result(result: message_processing.ProcessingResult) -> MessageProcessingResult:
    return MessageProcessingResult(**asdict(result))


@router.post("/carrier-messages/{message_id}/process", response_model=MessageProcessingResult)
def process_carrier_message(
    message_id: int, current: CsrfUser, db: DbSession
) -> MessageProcessingResult:
    return response_from_result(message_processing.manual_process(db, current, message_id))


@router.get("/carrier-messages/{message_id}/analysis", response_model=MessageAnalysisResponse)
def get_message_analysis(
    message_id: int, current: CurrentUser, db: DbSession
) -> MessageAnalysisResponse:
    return operations.message_analysis_response(db, current, message_id)


@router.get("/reviews/{review_id}/analysis", response_model=ReviewDetailResponse)
def get_review_analysis(
    review_id: int, current: CurrentUser, db: DbSession
) -> ReviewDetailResponse:
    return operations.get_review_detail(db, current, review_id)


@router.post("/reviews/{review_id}/apply-analysis", response_model=MessageProcessingResult)
def apply_review_analysis(
    review_id: int,
    data: HumanAnalysisInput,
    current: CsrfUser,
    db: DbSession,
) -> MessageProcessingResult:
    return response_from_result(message_processing.apply_review(db, current, review_id, data))


@router.post("/reviews/{review_id}/dismiss-analysis", response_model=MessageProcessingResult)
def dismiss_review_analysis(
    review_id: int,
    data: ReviewDismissRequest,
    current: CsrfUser,
    db: DbSession,
) -> MessageProcessingResult:
    return response_from_result(
        message_processing.dismiss_review(db, current, review_id, data.resolution_notes)
    )
