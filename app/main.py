"""Fernpage: a small notes and wiki app. Pages nest, bodies are markdown, favourites sit on top."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.sample import seed
from app.store import Store

STATIC = Path(__file__).parent / "static"


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
