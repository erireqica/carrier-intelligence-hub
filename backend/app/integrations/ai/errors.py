class AnalysisProviderError(RuntimeError):
    def __init__(self, code: str, *, reviewable: bool = False):
        super().__init__("AI analysis could not be completed safely.")
        self.code = code
        self.reviewable = reviewable
