from typing import Protocol

import openai
from openai import OpenAI

from app.core.config import Settings, get_settings
from app.integrations.ai.errors import AnalysisProviderError
from app.integrations.ai.prompt import ANALYSIS_INSTRUCTIONS
from app.integrations.ai.schemas import AnalysisResult


class Analyzer(Protocol):
    model_name: str

    def analyze(self, source_bundle: str) -> AnalysisResult: ...


class OpenAIAnalyzer:
    def __init__(self, settings: Settings | None = None, *, client: OpenAI | None = None):
        active = settings or get_settings()
        if not active.openai_configured or active.openai_api_key is None:
            raise AnalysisProviderError("AI_NOT_CONFIGURED")
        self.model_name = active.openai_model
        self._client = client or OpenAI(api_key=active.openai_api_key.get_secret_value())

    def analyze(self, source_bundle: str) -> AnalysisResult:
        try:
            response = self._client.responses.parse(
                model=self.model_name,
                instructions=ANALYSIS_INSTRUCTIONS,
                input=source_bundle,
                text_format=AnalysisResult,
                tools=[],
                store=False,
            )
        except openai.AuthenticationError as error:
            raise AnalysisProviderError("AI_AUTH_FAILED") from error
        except openai.RateLimitError as error:
            raise AnalysisProviderError("AI_RATE_LIMITED") from error
        except openai.APITimeoutError as error:
            raise AnalysisProviderError("AI_TIMEOUT") from error
        except openai.APIConnectionError as error:
            raise AnalysisProviderError("AI_TRANSIENT_FAILURE") from error
        except openai.InternalServerError as error:
            raise AnalysisProviderError("AI_SERVICE_UNAVAILABLE") from error
        except openai.APIStatusError as error:
            raise AnalysisProviderError("AI_UNKNOWN_PROVIDER_ERROR") from error
        except Exception as error:
            raise AnalysisProviderError("AI_INVALID_RESPONSE", reviewable=True) from error

        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, AnalysisResult):
            return parsed
        for output in response.output:
            if getattr(output, "type", None) != "message":
                continue
            for content in output.content:
                item = getattr(content, "parsed", None)
                if isinstance(item, AnalysisResult):
                    return item
        raise AnalysisProviderError("AI_REFUSAL", reviewable=True)
