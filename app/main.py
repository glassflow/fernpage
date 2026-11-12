"""Fernpage: a small notes and wiki app. Pages nest, bodies are markdown, favourites sit on top."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.sample import seed
from app.store import Store

STATIC = Path(__file__).parent / "static"
NOT_FOUND_HTML = (
    "<!doctype html>"
    '<html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="robots" content="noindex">'
    "<title>Link not found \u00b7 Fernpage</title>"
    '<link rel="stylesheet" href="/static/style.css"></head>'
    '<body class="shared"><main>'
    "<p class=\"empty\">This link doesn't work. It may have been turned off.</p>"
    "</main></body></html>"
)


# Sent on every response under /s and /api/shared (set by a middleware, so redirects,
# 404s and 405s carry them too).
SHARE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"
    ),
}


def _route_path(scope) -> str:
    """The request path without the ASGI root_path (a reverse-proxy prefix).

    Mirrors starlette._utils.get_route_path, which is what the router matches against: the
    prefix is stripped only when scope["path"] starts with it, on a path-segment boundary. The
    root_path is taken as is, so "/app/" with "/app//s/x" routes as "/s/x" and not "//s/x".
    """
    path = scope["path"]
    root = scope.get("root_path", "")
    if root and path.startswith(root) and (len(path) == len(root) or path[len(root)] == "/"):
        return path[len(root) :]
    return path


def _is_share_path(path: str) -> bool:
    return any(path == base or path.startswith(base + "/") for base in ("/s", "/api/shared"))


class PageIn(BaseModel):
    title: str = ""
    body: str = ""
    icon: str = ""
    parent_id: int | None = None


class PagePatch(BaseModel):
    title: str | None = None
    body: str | None = None
    icon: str | None = None
    favorite: bool | None = None
    parent_id: int | None = None


class CommentIn(BaseModel):
    body: str
    author: str = ""


class ResolvePatch(BaseModel):
    resolved: bool


def create_app(store: Store | None = None) -> FastAPI:
    if store is None:
        store = Store(os.getenv("FERNPAGE_DB", "fernpage.db"))
        if store.count() == 0:
            seed(store)

    app = FastAPI(title="Fernpage")
    app.state.store = store

    @app.middleware("http")
    async def share_headers(request: Request, call_next):
        response = await call_next(request)
        if _is_share_path(_route_path(request.scope)):
            response.headers.update(SHARE_HEADERS)
        return response

    # Starlette's ServerErrorMiddleware sits outside the middleware above, so an unhandled
    # exception would otherwise lose the share headers. HTTPException keeps its own handler.
    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception):
        response = PlainTextResponse("Internal Server Error", status_code=500)
        if _is_share_path(_route_path(request.scope)):
            response.headers.update(SHARE_HEADERS)
        return response

    def page_or_404(page_id: int) -> dict:
        page = store.get(page_id)
        if page is None:
            raise HTTPException(status_code=404, detail="no such page")
        return page

    @app.get("/api/pages")
    def tree():
        return {"pages": store.tree(), "favorites": store.favorites()}

    @app.post("/api/pages", status_code=201)
    def create(body: PageIn):
        try:
            return store.create(body.title, body.body, body.icon, body.parent_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such parent page") from None

    @app.get("/api/pages/{page_id}")
    def get(page_id: int):
        return page_or_404(page_id)

    @app.patch("/api/pages/{page_id}")
    def update(page_id: int, body: PagePatch):
        page_or_404(page_id)
        try:
            return store.update(page_id, **body.model_dump(exclude_unset=True))
        except KeyError:
            raise HTTPException(status_code=404, detail="no such parent page") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.delete("/api/pages/{page_id}", status_code=204)
    def delete(page_id: int):
        if not store.delete(page_id):
            raise HTTPException(status_code=404, detail="no such page")

    @app.post("/api/pages/{page_id}/share")
    def share(page_id: int):
        token = store.share(page_id)
        if token is None:
            raise HTTPException(status_code=404, detail="no such page")
        return {"token": token, "url": f"/s/{token}"}

    @app.delete("/api/pages/{page_id}/share", status_code=204)
    def unshare(page_id: int):
        if not store.unshare(page_id):
            raise HTTPException(status_code=404, detail="no such page")

    @app.get("/api/shared/{token}")
    def shared(token: str):
        page = store.get_shared(token)
        if page is None:
            raise HTTPException(status_code=404, detail="no such shared page")
        return page

    @app.get("/s/{token}", include_in_schema=False)
    def share_page(token: str):
        if store.get_shared(token) is None:
            return HTMLResponse(NOT_FOUND_HTML, status_code=404)
        return FileResponse(STATIC / "share.html")

    @app.get("/api/search")
    def search(q: str = ""):
        return {"results": store.search(q) if q.strip() else []}

    @app.get("/api/pages/{page_id}/comments")
    def list_comments(page_id: int):
        page_or_404(page_id)
        return {"threads": store.comments(page_id)}

    @app.post("/api/pages/{page_id}/comments", status_code=201)
    def add_comment(page_id: int, body: CommentIn):
        page_or_404(page_id)
        try:
            return store.add_comment(page_id, body.body, body.author)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such page") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.post("/api/comments/{comment_id}/replies", status_code=201)
    def add_reply(comment_id: int, body: CommentIn):
        try:
            return store.add_reply(comment_id, body.body, body.author)
        except KeyError:
            raise HTTPException(status_code=404, detail="no such comment") from None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None

    @app.patch("/api/comments/{comment_id}")
    def resolve_comment(comment_id: int, body: ResolvePatch):
        try:
            thread = store.set_resolved(comment_id, body.resolved)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if thread is None:
            raise HTTPException(status_code=404, detail="no such comment")
        return thread

    @app.delete("/api/comments/{comment_id}", status_code=204)
    def delete_comment(comment_id: int):
        if not store.delete_comment(comment_id):
            raise HTTPException(status_code=404, detail="no such comment")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
