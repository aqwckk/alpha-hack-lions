"""Single error format: {"error": {"code", "message", "request_id", "details"?, "fields"?}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 400
    code = "BAD_REQUEST"
    message = "Некорректный запрос"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
        details: dict[str, Any] | None = None,
        fields: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.code = code or self.code
        self.status = status or self.status
        self.details = details
        self.fields = fields
        self.headers = headers

    def body(self, request_id: str | None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message, "request_id": request_id}
        if self.details:
            err["details"] = self.details
        if self.fields:
            err["fields"] = self.fields
        return {"error": err}


class Unauthorized(ApiError):
    status, code, message = 401, "UNAUTHORIZED", "Требуется вход в систему"


class Forbidden(ApiError):
    status, code, message = 403, "FORBIDDEN", "Недостаточно прав для действия"


class NotFound(ApiError):
    status, code, message = 404, "NOT_FOUND", "Заявка не найдена или у вас нет к ней доступа"


class Conflict(ApiError):
    status, code, message = 409, "CONFLICT", "Конфликт состояния"


class ValidationFailed(ApiError):
    status, code, message = 422, "VALIDATION_FAILED", "Проверьте заполнение полей"


class TooManyRequests(ApiError):
    status, code, message = 429, "TOO_MANY_REQUESTS", "Слишком много запросов, попробуйте позже"


class ServiceUnavailable(ApiError):
    status, code, message = 503, "SERVICE_UNAVAILABLE", "Сервис временно недоступен, попробуйте еще раз"


def invalid_transition(status: str, client_status: str | None = None, *, internal: bool) -> Conflict:
    details = {"current_status": status} if internal else {"current_client_status": client_status}
    return Conflict("Действие недоступно в текущем состоянии заявки", code="INVALID_TRANSITION", details=details)


def version_conflict(version: int) -> Conflict:
    return Conflict("Заявка изменилась, обновите данные", code="VERSION_CONFLICT", details={"current_version": version})
