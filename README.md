# Fernpage

A small notes and wiki app: pages inside pages, markdown bodies, favourites and search. It is
the demo repo for the [Tares software factory](https://docs.glassflow.ai/tares/software-factory/get-started):
a crew of Claude Code sessions plans features with you and builds them into pull requests merged
on main. Every feature on the roadmap below was, or will be, built that way.

## Run

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. A new workspace starts with a few sample pages. Pages are kept in
`fernpage.db` (set `FERNPAGE_DB` to keep them elsewhere); delete the file to start over.

## Test

```bash
uv run pytest
uv run ruff check .
```

## How it fits together

- `app/store.py`: pages in SQLite. A page has a title, an icon, a markdown body, an optional
  parent and a favourite flag. Deleting a page deletes the pages inside it.
- `app/main.py`: the JSON API under `/api` and the single page app at `/`.
- `app/static/`: the app itself, plain JavaScript with no build step, and `markdown.js`, a small
  renderer that escapes everything first.
- `app/sample.py`: the pages a new workspace starts with.

## Build a feature with the Tares factory

You need Claude Code (signed in), `gh` (signed in, with write access to your copy of this repo)
and `uv`.

1. Make your own copy of this repo and clone it:

   ```bash
   gh repo fork glassflow/fernpage --clone && cd fernpage
   ```

2. Install Tares and point it at a workspace:

   ```bash
   uv tool install tares
   tares login              # or run Tares yourself: `tares up` and `tares mcp --transport streamable-http`
   ```

3. Build a small feature in one session:

   ```bash
   tares factory session "Trash: deleting a page moves it to a Trash list in the sidebar, where it can be restored or deleted for good"
   ```

   Claude asks a few questions, writes a short spec and the tickets on Tares, then builds them.
   Open the project in the Tares console to follow the tickets, the decisions and the review.

4. Or hand a bigger feature to the crew:

   ```bash
   tares factory crew up
   tares factory spec "Page templates: start a new page from a template, and save any page as one"
   tares factory crew attach orchestrator    # answer the crew's questions here
   ```

   The crew builds each ticket on its own branch, a reviewer checks every pull request, and it
   merges once CI is green.

## Roadmap

- **Comments on pages** (done): a thread under each page, reply, resolve a thread when it is done.
- **Share a page with a public link**: read-only, can be turned off again.
- **Page templates**: start a page from a template, save any page as one.
- **Trash, with restore**: deleted pages wait in Trash for 30 days.
- **Mentions**: `@name` in a page or comment.
- **Move pages by dragging** them in the sidebar.
- **Export a page** as markdown.
