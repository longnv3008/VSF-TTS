from __future__ import annotations


class AudioPipelineError(Exception):
    # Lỗi nghiệp vụ có sẵn HTTP status để API handler trả thẳng ra FE.
    def __init__(self, detail: str, status_code: int = 500) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class BatchAbortError(Exception):
    # Dùng khi muốn dừng cả batch tại một URL lỗi và giữ lại danh sách URL chưa chạy.
    def __init__(
        self,
        *,
        step: str,
        failed_url: str,
        remaining_urls: list[str],
        cause: Exception,
    ) -> None:
        super().__init__(format_function_error(step, cause))
        self.step = step
        self.failed_url = failed_url
        self.remaining_urls = remaining_urls
        self.cause = cause


class SkipUrlError(Exception):
    # Dùng khi muốn bỏ qua một URL lỗi cục bộ nhưng vẫn tiếp tục job con hiện tại.
    def __init__(self, *, step: str, failed_url: str, cause: Exception) -> None:
        super().__init__(format_function_error(step, cause))
        self.step = step
        self.failed_url = failed_url
        self.cause = cause


def format_function_error(function_name: str, exc: Exception) -> str:
    error_name = type(exc).__name__
    error_detail = str(exc).strip()
    if error_detail:
        return f"{function_name}: {error_name} - {error_detail}"
    return f"{function_name}: {error_name}"
