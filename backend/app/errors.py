"""Structured API errors: {"error": {"code", "message", "details", "request_id"}}."""
from typing import Any

from .logging_setup import request_id_var


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          "details": self.details, "request_id": request_id_var.get()}}
