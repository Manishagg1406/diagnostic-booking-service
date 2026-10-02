class AppError(Exception):
    """Domain error that maps to an HTTP response (see handler in main.py)."""

    status_code = 500

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class UnprocessableError(AppError):
    status_code = 422
