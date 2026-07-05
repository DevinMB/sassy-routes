from starlette.requests import Request


async def entitlement_middleware(request: Request, call_next):
    """Entitlement seam (CLAUDE-ref §9): when the auth phase starts, this is
    where the subscription/session check will live. Until then: allow all.
    Do not add auth, accounts, or PII here without explicit go-ahead."""
    request.state.entitlement = "allow"
    return await call_next(request)
