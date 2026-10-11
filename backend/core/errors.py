"""Typed application errors mapped to one JSON error envelope.

Raw exceptions never reach the client: unknown errors become ``internal_error``
with the request id so the full trace can be found in the logs.
"""
from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class NotFound(AppError):
    status_code, code, message = 404, "not_found", "The requested resource was not found."


class Unauthorized(AppError):
    status_code, code, message = 401, "unauthorized", "A valid admin key is required."


class RateLimited(AppError):
    status_code, code, message = 429, "rate_limited", "Too many requests. Please wait a moment and try again."


class UnsupportedFile(AppError):
    status_code, code, message = 415, "unsupported_file", "This file type is not supported."


class FileTooLarge(AppError):
    status_code, code, message = 413, "file_too_large", "The file is too large."


class BadRequest(AppError):
    status_code, code, message = 400, "bad_request", "The request could not be processed."


class LLMNotConfigured(AppError):
    status_code, code, message = 503, "llm_not_configured", "The AI model is not configured on this server."


class LLMUnavailable(AppError):
    status_code, code, message = 503, "llm_unavailable", "The AI model is temporarily unavailable. Please retry."
