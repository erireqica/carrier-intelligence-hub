# Structured AI Processing

Stage 4 converts an already-approved `CarrierMessage` into a structured proposal and applies it only when deterministic checks pass.

```text
Gmail poller
    |
    v
CarrierMessage(RECEIVED)
    |
    v
message processor
    +--> Gmail PDF fetch -> PyMuPDF in memory
    +--> minimized, source-labelled text bundle
    +--> OpenAI Responses API + strict Pydantic Structured Output
    +--> deterministic validation
             |                         |
             v                         v
        auto apply                 ReviewItem
             |                         |
             v                         v
       Case / Tasks / Evidence    human apply or dismiss
             |
             v
         PROCESSED
```

## Trust and data boundaries

There are three independent boundaries. The Stage 3 sender allowlist decides whether Gmail content is eligible for ingestion. The model interprets that approved but still untrusted content. The backend then decides whether the proposal may change operational records. The model has no tools, cannot choose a carrier, and cannot write PostgreSQL.

Only the authoritative carrier name, subject, received time, cleaned email text, and extracted PDF text are sent to OpenAI. Gmail credentials, OAuth values, application sessions, passwords, keys, PDF bytes, and unrelated messages are excluded. The Responses API call sets `store=False` and `tools=[]`. Source text is explicitly described as untrusted data so instructions inside an email or PDF cannot override the system instructions.

## PDF and attachment lifecycle

PDF bytes are downloaded with the existing `gmail.readonly` scope and held only in process memory. PyMuPDF extracts page text in stable page order, subject to configured byte and page limits. A normal PDF becomes `EXTRACTED`; an image-only document becomes `NEEDS_OCR`; malformed or over-limit input becomes `FAILED`; other MIME types become `UNSUPPORTED`. OCR is intentionally absent. Only extracted text, page count, state, and a safe error category are persisted.

## Structured proposal and validation

The strict schema covers classification, summary, priority, client, policy number/status, premium and currency, effective date, deadline, requirements, action items, evidence excerpts, confidence, and uncertainties. Pydantic rejects extra or malformed structure after the provider response.

Backend checks include required policy identity, classification/status compatibility, ISO dates, bounded decimal money, ISO currency, deterministic calendar/business-day deadlines in the agency timezone, evidence source identity and exact normalized substring grounding, confidence threshold, model uncertainty, source completeness/truncation, policy/client conflicts, and action-to-case linkage. Confidence is only one review signal and is not a calibrated probability.

Safe proposals match a Case by `(agency, authoritative carrier, normalized policy number)`. Existing assignment and known non-null values are preserved. New cases go to the mailbox owner. Action items become Tasks with a unique source-message/action-index key, preventing duplicates on retry. Only verified evidence excerpts become `CaseEvidence`.

Validation ambiguity creates or reuses one open `ReviewItem` and marks the message `NEEDS_REVIEW`. A reviewer sees the source, proposal, evidence, flags, attachment previews, and editable final fields. Applying corrections stores them separately from the original model proposal, materializes through the same backend path, resolves the review, and marks the message `PROCESSED`. Dismissal marks the review `DISMISSED` and message `IGNORED`. Technical provider/download/materialization failures use safe codes and `FAILED`, which can be retried.

## Operation

Configure secrets only in ignored `backend/.env`:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6
AI_AUTO_APPLY_CONFIDENCE_THRESHOLD=0.80
AI_MAX_SOURCE_CHARS=120000
MESSAGE_PROCESS_POLL_INTERVAL_SECONDS=10
PDF_MAX_ATTACHMENT_BYTES=10485760
PDF_MAX_PAGES=50
```

Run the worker with `python -m app.workers.message_process`, add `--once` for one pass, or add `--message-id ID` for one explicit retry. FastAPI does not run this loop. Run the database-free, synthetic provider evaluation with `python scripts/evaluate_stage4_samples.py`.

Operational audit events record message IDs, safe state changes, model name, confidence, flags, task counts, and human actor IDs where appropriate. They never record provider secrets, model input/output, email bodies, extracted PDF text, tokens, or bytes.

Known limitations: no OCR, Gmail labels, mailbox mutation, push delivery, CRM delivery, confidence calibration, sender-authentication verification, or production compliance assurance. This implementation is not a HIPAA, SOC 2, Google production-verification, or security-assessment claim.
