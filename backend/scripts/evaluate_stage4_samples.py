"""Run the three synthetic Stage 4 samples against the configured real model."""

from app.core.config import get_settings
from app.evaluation import EVALUATION_SAMPLES, evaluate_result
from app.integrations.ai import AnalysisProviderError, OpenAIAnalyzer


def main() -> int:
    settings = get_settings()
    if not settings.openai_configured:
        print("Stage 4 sample evaluation: BLOCKED (OpenAI is not configured)")
        return 2
    try:
        analyzer = OpenAIAnalyzer(settings)
    except AnalysisProviderError as error:
        print(f"Stage 4 sample evaluation: BLOCKED ({error.code})")
        return 2

    failed = 0
    for sample in EVALUATION_SAMPLES:
        try:
            result = analyzer.analyze(sample.bundle.rendered)
        except AnalysisProviderError as error:
            print(f"{sample.name}: ERROR ({error.code})")
            failed += 1
            continue
        failures = evaluate_result(sample, result)
        if failures:
            print(f"{sample.name}: FAIL ({', '.join(failures)})")
            failed += 1
        else:
            print(f"{sample.name}: PASS")
    print(f"Stage 4 sample evaluation: {'PASS' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
