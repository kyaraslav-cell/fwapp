from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.db import init_db, session_scope
from app.core.env import load_env_file
from app.core.seed import ensure_lake_seeded
from app.ingest.open_meteo import ingest_forecast
from app.ingest.scheduler import build_scheduler
from app.predict.daily import generate_predictions
from app.web import health as health_check
from app.web import security
from app.web.deps import (
    NotSignedInError,
    require_user,
    resolve_request_user,
    templates,
)
from app.web.routes import auth, discover, history, places, sessions

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as db:
        lake = ensure_lake_seeded(db)
        ingest_forecast(db, lake)
        generate_predictions(db, lake)

    scheduler = build_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    # Before anything reads os.environ. `docker compose` already applies `.env`
    # itself; this is what makes `make dev` behave the same way, so the file
    # the docs tell the owner to write is not silently ignored outside docker.
    applied = load_env_file()
    if applied:
        # Names only. The values are the point of the file.
        logging.getLogger("fishlog").info(".env applied: %s", ", ".join(applied))

    app = FastAPI(title="Fishlog", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

    media_dir = get_settings().media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        """Applied to everything, including /static, /media and error pages.

        Outermost on purpose: a response that escapes the inner middleware -
        an unhandled exception, a 404 from the router, a file served straight
        off disk by StaticFiles - is exactly the one that would otherwise go
        out bare. See app/web/security.py for why each header is here.
        """
        response: Response = await call_next(request)
        for name, value in security.headers_for(request.url.scheme).items():
            response.headers.setdefault(name, value)
        return response

    @app.middleware("http")
    async def attach_current_user(request: Request, call_next: Any) -> Response:
        """Resolve the auth cookie once per request, before anything renders.

        Done here rather than in a dependency so that the topbar knows who is
        signed in on every page, including the ones that do not require it.
        Static and media are skipped: they are served by StaticFiles and would
        otherwise open a database session per image.
        """
        request.state.user = None
        if not request.url.path.startswith(("/static", "/media")):
            with session_scope() as db:
                request.state.user = resolve_request_user(db, request)
        response: Response = await call_next(request)
        return response

    @app.exception_handler(NotSignedInError)
    async def not_signed_in(request: Request, exc: NotSignedInError) -> Response:
        """Send them to sign in, and back to where they were afterwards."""
        return RedirectResponse(
            url=f"/auth/login?next={quote(exc.next_path, safe='/?=&')}",
            status_code=303,
        )

    def _error_page(request: Request, status_code: int, kind: str) -> Response:
        """An error an angler can act on, in their own language.

        HTMX partials and anything asking for JSON get JSON: swapping an error
        page into a fragment of a working page produces something that looks
        broken in a much more confusing way than a plain message.
        """
        wants_html = "text/html" in request.headers.get("accept", "") and not (
            request.headers.get("hx-request")
        )
        if not wants_html:
            return JSONResponse({"detail": kind}, status_code=status_code)
        return templates.TemplateResponse(
            "error.html",
            {
                "request": request,
                "active_nav": None,
                "status_code": status_code,
                "title_key": f"error.{kind}.title",
                "body_key": f"error.{kind}.body",
            },
            status_code=status_code,
        )

    @app.exception_handler(404)
    async def not_found(request: Request, exc: Any) -> Response:
        return _error_page(request, 404, "not_found")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == 404:
            return _error_page(request, 404, "not_found")
        if exc.status_code >= 500:
            return _error_page(request, exc.status_code, "server")
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> Response:
        """Never show a stack trace to an angler, always write one to the log.

        FastAPI's default is to re-raise, which in production means the ASGI
        server's bare 500 - no styling, no language, no way back.
        """
        logging.getLogger("fishlog").exception("unhandled error on %s", request.url.path)
        return _error_page(request, 500, "server")

    @app.get("/health")
    def health(request: Request) -> Response:
        """Not "is the process up" - "is the weather it is serving still true".

        Public and deliberately dull; see app/web/health.py.
        """
        with session_scope() as db:
            report = health_check.check(db)
        return JSONResponse(
            report.as_dict(),
            status_code=report.http_status,
            # A cached healthcheck is a healthcheck that lies for as long as
            # the cache lives.
            headers={"Cache-Control": "no-store"},
        )

    app.include_router(auth.router)
    app.include_router(places.router)
    # Adding a water is a write, so it needs an account like the notebook does.
    app.include_router(discover.router, dependencies=[Depends(require_user)])
    # The security boundary, in one place: the notebook is one angler's
    # private record and needs an account; the lake, the conditions and the
    # map read the same for everyone and stay open, which is also what keeps
    # the published read-only site (tools/build_static.py) buildable.
    app.include_router(sessions.router, dependencies=[Depends(require_user)])
    app.include_router(history.router, dependencies=[Depends(require_user)])
    return app


app = create_app()
