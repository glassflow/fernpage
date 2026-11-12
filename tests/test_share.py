import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.store
from app.main import SHARE_HEADERS, _route_path, create_app
from app.store import Store

PRIVATE = {
    "cache-control": "no-store",
    "x-robots-tag": "noindex",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def client():
    return TestClient(create_app(Store()))


def make(client, **body):
    res = client.post("/api/pages", json=body)
    assert res.status_code == 201
    return res.json()


def share(client, page_id):
    res = client.post(f"/api/pages/{page_id}/share")
    assert res.status_code == 200
    return res.json()["token"]


def test_share_returns_token_and_url(client):
    page = make(client, title="Ideas")
    res = client.post(f"/api/pages/{page['id']}/share")
    assert res.status_code == 200
    data = res.json()
    assert len(data["token"]) >= 20
    assert data["url"] == "/s/" + data["token"]


def test_sharing_twice_returns_the_same_token(client):
    page = make(client, title="Ideas")
    assert share(client, page["id"]) == share(client, page["id"])


def test_shared_page_is_public_and_minimal(client):
    page = make(client, title="Ideas", icon="x", body="# Hi")
    token = share(client, page["id"])
    res = client.get(f"/api/shared/{token}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Ideas"
    assert data["icon"] == "x"
    assert data["body"] == "# Hi"
    assert data["updated_at"] == page["updated_at"]
    for key in ("id", "parent_id", "share_token"):
        assert key not in data
    for name, value in PRIVATE.items():
        assert res.headers[name] == value


def test_page_shows_the_same_token(client):
    page = make(client, title="Ideas")
    assert "share_token" in page and page["share_token"] is None
    token = share(client, page["id"])
    assert client.get(f"/api/pages/{page['id']}").json()["share_token"] == token


def test_sharing_does_not_change_updated_at(client, monkeypatch):
    page = make(client, title="Ideas")
    monkeypatch.setattr(app.store, "_now", lambda: "2999-01-01T00:00:00+00:00")
    token = share(client, page["id"])
    assert client.get(f"/api/pages/{page['id']}").json()["updated_at"] == page["updated_at"]
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    assert client.get(f"/api/pages/{page['id']}").json()["updated_at"] == page["updated_at"]
    assert token


def test_unshare_revokes_and_a_new_share_gets_a_new_token(client):
    page = make(client, title="Ideas")
    old = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    assert client.get(f"/api/shared/{old}").status_code == 404
    assert client.get(f"/api/pages/{page['id']}").json()["share_token"] is None
    new = share(client, page["id"])
    assert new != old
    assert client.get(f"/api/shared/{old}").status_code == 404
    assert client.get(f"/api/shared/{new}").status_code == 200


def test_unsharing_a_page_that_was_never_shared_is_204(client):
    page = make(client, title="Ideas")
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204


def test_missing_pages_and_tokens_are_404(client):
    assert client.post("/api/pages/999/share").status_code == 404
    assert client.delete("/api/pages/999/share").status_code == 404
    res = client.get("/api/shared/nope")
    assert res.status_code == 404
    for name, value in PRIVATE.items():
        assert res.headers[name] == value


def test_deleting_a_page_kills_its_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}").status_code == 204
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_deleting_the_parent_kills_the_childs_token(client):
    parent = make(client, title="Product")
    child = make(client, title="Roadmap", parent_id=parent["id"])
    token = share(client, child["id"])
    assert client.delete(f"/api/pages/{parent['id']}").status_code == 204
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_patch_cannot_set_the_share_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.patch(f"/api/pages/{page['id']}", json={"share_token": "x"})
    assert res.status_code == 200
    assert res.json()["share_token"] == token
    assert client.get("/api/shared/x").status_code == 404


def test_store_update_ignores_the_share_token():
    store = Store()
    page = store.create(title="Ideas")
    token = store.share(page["id"])
    store.update(page["id"], share_token="x")
    assert store.get(page["id"])["share_token"] == token


def test_old_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '',
            icon TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            favorite INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    old.execute(
        "INSERT INTO pages (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
        ("Old", "kept", "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"),
    )
    old.commit()
    old.close()

    store = Store(str(path))
    page = store.get(1)
    assert page is not None and page["title"] == "Old" and page["share_token"] is None
    token = store.share(1)
    assert token

    again = Store(str(path))
    assert again.get(1)["title"] == "Old"
    assert again.share(1) == token
    assert again.get_shared(token)["body"] == "kept"


def test_share_token_is_unique_in_the_database():
    store = Store()
    a = store.create(title="A")
    b = store.create(title="B")
    token = store.share(a["id"])
    with pytest.raises(sqlite3.IntegrityError):
        store._db.execute("UPDATE pages SET share_token = ? WHERE id = ?", (token, b["id"]))


def test_get_shared_with_an_empty_token_is_none():
    store = Store()
    assert store.get_shared("") is None
    page = store.create(title="A")
    store.share(page["id"])
    assert store.get_shared("") is None
    # a row that somehow holds an empty token must still never be served
    other = store.create(title="B")
    store._db.execute("UPDATE pages SET share_token = '' WHERE id = ?", (other["id"],))
    store._db.commit()
    assert store.get_shared("") is None


CSP = "default-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'"


def assert_share_headers(res):
    for name, value in SHARE_HEADERS.items():
        assert res.headers[name] == value
    for name, value in PRIVATE.items():
        assert res.headers[name] == value
    # the literal policy, so quietly weakening the constant fails here
    assert res.headers["content-security-policy"] == CSP


def test_public_page_opens_for_a_valid_token(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.get(f"/s/{token}")
    assert res.status_code == 200
    assert "share.js" in res.text
    assert_share_headers(res)


def test_public_page_for_a_bogus_token_is_404(client):
    res = client.get("/s/bogus")
    assert res.status_code == 404
    assert "doesn't work" in res.text
    assert_share_headers(res)


def test_public_page_is_404_after_unshare(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    res = client.get(f"/s/{token}")
    assert res.status_code == 404
    assert_share_headers(res)


def test_share_html_is_served_statically(client):
    assert client.get("/static/share.html").status_code == 200


def test_shared_api_carries_the_csp_too(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    assert_share_headers(client.get(f"/api/shared/{token}"))
    assert_share_headers(client.get("/api/shared/nope"))


def test_headers_on_the_trailing_slash_redirect(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    res = client.get(f"/s/{token}/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"].endswith(f"/s/{token}")
    assert_share_headers(res)


def test_headers_on_odd_share_paths(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for path in (
        f"/s/{token}/x",
        "/s/a%2Fb",
        "/s/",
        "/s",
        "/api/shared",
        "/api/shared/",
        "/api/shared/nope/extra",
    ):
        res = client.get(path, follow_redirects=False)
        assert res.status_code in (307, 404), path
        assert_share_headers(res)


def test_headers_on_wrong_methods(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for method, path in (
        ("HEAD", f"/s/{token}"),
        ("HEAD", f"/api/shared/{token}"),
        ("POST", f"/s/{token}"),
        ("DELETE", f"/api/shared/{token}"),
    ):
        res = client.request(method, path)
        assert res.status_code == 405, (method, path)
        assert_share_headers(res)


def test_handlers_do_not_duplicate_the_headers(client):
    page = make(client, title="Ideas")
    token = share(client, page["id"])
    for path in (f"/s/{token}", "/s/nope", f"/api/shared/{token}", "/api/shared/nope"):
        res = client.get(path)
        for name in SHARE_HEADERS:
            assert len(res.headers.get_list(name)) == 1, (path, name)


def test_other_routes_do_not_get_the_share_headers(client):
    make(client, title="Ideas")
    for path in ("/api/pages", "/", "/static/style.css", "/s2", "/api/sharedx"):
        res = client.get(path)
        for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
            assert name not in res.headers, (path, name)
        assert res.headers.get("cache-control") != "no-store", path


def test_headers_survive_a_reverse_proxy_root_path():
    # `uvicorn --root-path /prefix` puts the prefix in scope["root_path"] and (in current
    # uvicorn) in scope["path"] too, so the middleware sees "/prefix/s/<token>".
    seen = []
    app = create_app(Store())

    @app.middleware("http")
    async def spy(request, call_next):
        seen.append((request.scope["root_path"], request.url.path))
        return await call_next(request)

    client = TestClient(app, root_path="/prefix")
    page = client.post("/prefix/api/pages", json={"title": "Ideas"}).json()
    token = client.post(f"/prefix/api/pages/{page['id']}/share").json()["token"]
    for path in (f"/s/{token}", f"/api/shared/{token}", "/s/nope", "/api/shared/nope"):
        seen.clear()
        res = client.get(f"/prefix{path}")
        assert res.status_code in (200, 404), path
        assert seen == [("/prefix", f"/prefix{path}")], seen  # the prefix really is in the path
        assert_share_headers(res)
    # a server that leaves the prefix out of scope["path"] works too
    assert_share_headers(client.get(f"/s/{token}"))
    # a non-share route under the prefix gets no share headers
    res = client.get("/prefix/api/pages")
    assert res.status_code == 200
    for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
        assert name not in res.headers
    assert res.headers.get("cache-control") != "no-store"


@pytest.mark.parametrize(
    ("root_path", "path"),
    [
        ("/app", "/appx/s/x"),  # not a path-segment boundary: prefix is not stripped
        ("/app/", "/app//s/x"),  # trailing slash in root_path: only one "/" is left over
        ("/app", "/app"),  # path equals root_path (length branch)
        ("/app", "/s/x"),  # the server left the prefix out of scope["path"]
        ("/app", "/app/s/x"),
        ("", "/s/x"),
        ("/", "/s/x"),  # root_path "/": the one root where "/s/x" stays unstripped
    ],
)
def test_route_path_matches_starlette(root_path, path):
    from starlette._utils import get_route_path

    scope = {"path": path, "root_path": root_path}
    assert _route_path(scope) == get_route_path(scope)


def test_headers_with_a_trailing_slash_root_path():
    # `uvicorn --root-path /app/` gives scope["path"] == "/app//s/<token>", which Starlette
    # routes as "/s/<token>"; the share headers must follow the router's view of the path.
    seen = []
    app = create_app(Store())

    @app.middleware("http")
    async def spy(request, call_next):
        seen.append((request.scope["root_path"], request.url.path))
        return await call_next(request)

    client = TestClient(app, root_path="/app/")
    page = client.post("/app//api/pages", json={"title": "Ideas"}).json()
    token = client.post(f"/app//api/pages/{page['id']}/share").json()["token"]
    for path in (f"/s/{token}", f"/api/shared/{token}"):
        seen.clear()
        res = client.get(f"/app/{path}")
        assert seen == [("/app/", f"/app/{path}")], seen  # the double slash really arrives
        assert res.status_code == 200, path
        assert_share_headers(res)


def test_unhandled_errors_carry_the_share_headers(monkeypatch):
    store = Store()
    client = TestClient(create_app(store), raise_server_exceptions=False)
    page = make(client, title="Ideas")
    token = share(client, page["id"])

    def locked(token):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "get_shared", locked)
    for path in (f"/s/{token}", f"/api/shared/{token}"):
        res = client.get(path)
        assert res.status_code == 500, path
        assert res.text == "Internal Server Error"
        assert_share_headers(res)
        for name in SHARE_HEADERS:
            assert len(res.headers.get_list(name)) == 1, (path, name)

    # a non-share route keeps the plain 500, without the share headers
    def broken():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "tree", broken)
    res = client.get("/api/pages")
    assert res.status_code == 500
    assert res.text == "Internal Server Error"
    for name in ("content-security-policy", "x-robots-tag", "referrer-policy"):
        assert name not in res.headers
    assert res.headers.get("cache-control") != "no-store"

    # HTTPException responses are not swallowed by the catch-all handler
    assert client.get("/api/pages/9999").status_code == 404


OLD_PAGES = """
    CREATE TABLE pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
        title TEXT NOT NULL DEFAULT '',
        icon TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        favorite INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
"""


def old_db(path):
    con = sqlite3.connect(path)
    con.executescript(OLD_PAGES)
    con.commit()
    con.close()
    return str(path)


def test_empty_old_schema_database_opens_and_shares(tmp_path):
    store = Store(old_db(tmp_path / "old.db"))
    page = store.create(title="New")
    assert store.share(page["id"])


class RacingConnection:
    """Thin proxy (sqlite3.Connection.execute is a C method, so it cannot be patched on the
    instance). It reports the column as missing the first time it is asked, and lets a
    rival process add the column before our own ALTER runs."""

    def __init__(self, real, path, connect, alter_error=None):
        self._real = real
        self._path = path
        self._connect = connect
        self._alter_error = alter_error
        self._seen = False

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._real, name, value)

    def execute(self, sql, *args):
        if sql.startswith("PRAGMA table_info(pages)") and not self._seen:
            self._seen = True
            rows = self._real.execute(sql, *args).fetchall()
            assert all(r[1] != "share_token" for r in rows)
            if self._alter_error is None:
                rival = self._connect(self._path)
                rival.execute("ALTER TABLE pages ADD COLUMN share_token TEXT")
                rival.commit()
                rival.close()
            return iter(rows)
        if sql.startswith("ALTER TABLE") and self._alter_error is not None:
            raise self._alter_error
        return self._real.execute(sql, *args)


def patch_connect(monkeypatch, path, alter_error=None):
    real_connect = sqlite3.connect

    def connect(*a, **kw):
        return RacingConnection(real_connect(*a, **kw), path, real_connect, alter_error)

    monkeypatch.setattr(app.store.sqlite3, "connect", connect)


def test_migration_survives_another_process_adding_the_column(tmp_path, monkeypatch):
    path = old_db(tmp_path / "race.db")
    patch_connect(monkeypatch, path)
    store = Store(path)
    page = store.create(title="Raced")
    token = store.share(page["id"])
    assert store.get_shared(token)["title"] == "Raced"


def test_migration_error_is_raised_when_the_column_is_still_missing(tmp_path, monkeypatch):
    path = old_db(tmp_path / "boom.db")
    patch_connect(monkeypatch, path, alter_error=sqlite3.OperationalError("boom"))
    with pytest.raises(sqlite3.OperationalError, match="boom"):
        Store(path)


def test_editor_page_has_the_share_controls(client):
    res = client.get("/")
    assert res.status_code == 200
    for el in ("share", "share-panel", "share-url", "share-error", "copy", "unshare"):
        assert f'id="{el}"' in res.text
    # the panel starts closed, and the share button says what it controls and that it is closed
    assert re.search(r'<div id="share-panel"[^>]*\bhidden\b', res.text)
    button = re.search(r'<button id="share"[^>]*>', res.text).group(0)
    assert 'aria-controls="share-panel"' in button
    assert 'aria-expanded="false"' in button
    # the "on" colour of the Share button
    assert "#share.on" in client.get("/static/style.css").text


# ── editor behaviour: app.js run under node with a small fake DOM ──

APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "app.js"

HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const [appPath, scenarioPath, pathname] = process.argv.slice(2);

const els = {};
function el(id) {
  if (els[id]) return els[id];
  const attrs = {}, classes = new Set();
  const base = {
    id, hidden: false, disabled: false, textContent: "", value: "", selected: false,
    dataset: {}, onclick: null,
    classList: {
      toggle(n, force) { (force ? classes.add(n) : classes.delete(n)); },
      add(n) { classes.add(n); }, remove(n) { classes.delete(n); },
      contains(n) { return classes.has(n); },
    },
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    select() { base.selected = true; },
  };
  // any other method the app calls (focus, replaceChildren, ...) is a no-op
  return els[id] = new Proxy(base, {
    get: (t, k) => (k in t || typeof k !== "string" ? t[k] : () => []),
  });
}

el("copy").textContent = "Copy link"; // as in index.html
const env = {
  el, pages: {}, handlers: {}, timers: [],
  clipboard: { writeText: async () => {} }, execCommand: () => true,
  addPage(id, extra = {}) {
    env.pages[id] = { id, parent_id: null, title: "T" + id, icon: "", body: "", favorite: false,
                      share_token: null, updated_at: "2026-01-01T00:00:00Z", ...extra };
  },
  deferred() {
    const d = {};
    d.promise = new Promise((resolve) => { d.resolve = resolve; });
    return d;
  },
  tick: () => new Promise((r) => setImmediate(r)),
  run: (code) => vm.runInContext(code, ctx),
  click: async (id) => el(id).onclick(),
};

async function fakeFetch(path, init) {
  const key = (init.method || "GET") + " " + path;
  let reply = env.handlers[key] ? await env.handlers[key]() : null;
  if (!reply) {
    const page = path.match(/^\/api\/pages\/(\d+)$/);
    if (key === "GET /api/pages") reply = { status: 200, body: { pages: [], favorites: [] } };
    else if (page && init.method === "GET" && env.pages[page[1]])
      reply = { status: 200, body: JSON.parse(JSON.stringify(env.pages[page[1]])) };
    else if (/\/comments$/.test(path)) reply = { status: 200, body: { threads: [] } };
    else if (init.method === "DELETE") reply = { status: 204, body: null };
    else reply = { status: 404, body: { detail: "no handler for " + key } };
  }
  return {
    ok: reply.status < 400, status: reply.status, statusText: "status " + reply.status,
    json: async () => reply.body,
  };
}

const unhandled = [];
process.on("unhandledRejection", (e) => unhandled.push(String(e)));

const sandbox = {
  document: { getElementById: el, addEventListener() {}, execCommand: (c) => env.execCommand(c),
              body: {}, activeElement: null },
  location: { origin: "http://h", pathname, search: "?a=b", hash: "#1" },
  navigator: { clipboard: { writeText: (t) => env.clipboard.writeText(t) } },
  fetch: fakeFetch,
  setTimeout: (fn, ms) => { env.timers.push({ fn, ms }); return env.timers.length; },
  clearTimeout() {},
  localStorage: { getItem: () => null, setItem() {} },
  window: { addEventListener() {}, renderMarkdown: (s) => s },
  console,
};
const ctx = vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(appPath, "utf8"), ctx);

(async () => {
  await env.tick();
  const result = await require(scenarioPath)(env);
  await env.tick();
  console.log(JSON.stringify({ result, unhandled }));
})().catch((e) => { console.error(e); process.exit(1); });
"""

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def run_editor(tmp_path, scenario, pathname="/"):
    """Run `scenario` (the body of an async function of `env`) against app.js; return its result."""
    (tmp_path / "harness.js").write_text(HARNESS)
    (tmp_path / "scenario.js").write_text(
        "module.exports = async (env) => {\n" + scenario + "\n};\n")
    done = subprocess.run(
        ["node", str(tmp_path / "harness.js"), str(APP_JS), str(tmp_path / "scenario.js"),
         pathname],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["unhandled"] == []  # no uncaught promise rejection
    return out["result"]


def snapshot(env_expr="env"):
    """JS: a summary of the share controls, as the person sees them."""
    return f"""const e = {env_expr}.el;
    const snap = () => ({{
      label: e("share").textContent, disabled: e("share").disabled,
      unshareDisabled: e("unshare").disabled,
      expanded: e("share").getAttribute("aria-expanded"), panelHidden: e("share-panel").hidden,
      error: e("share-error").hidden ? "" : e("share-error").textContent,
      url: e("share-url").value, selected: e("share-url").selected,
      copy: e("copy").textContent, token: env.run("current && current.share_token"),
    }});"""


@needs_node
@pytest.mark.parametrize(
    ("pathname", "link"),
    [("/", "http://h/s/tok"), ("/prefix/", "http://h/prefix/s/tok"),
     ("/prefix", "http://h/prefix/s/tok")],
)
def test_editor_link_keeps_the_path_prefix(tmp_path, pathname, link):
    got = run_editor(tmp_path, """
      env.addPage(1, { share_token: "tok" });
      await env.run("open(1)");
      return env.el("share-url").value;
    """, pathname)
    assert got == link  # and the "?a=b" search and "#1" hash of the fake location are ignored


@needs_node
def test_failed_share_shows_an_error_and_stays_off(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1);
      env.handlers["POST /api/pages/1/share"] = () => ({ status: 500, body: { detail: "boom" } });
      await env.run("open(1)");
      await env.click("share");
      return snap();
    """)
    assert got["error"] == "Couldn't turn on the link. Try again."
    assert got["token"] is None
    assert got["label"] == "Share"
    assert got["panelHidden"] is True
    assert got["expanded"] == "false"
    assert got["disabled"] is False  # can try again


@needs_node
def test_share_then_turn_off_updates_the_panel(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1);
      env.handlers["POST /api/pages/1/share"] = () => ({ status: 200, body: { token: "tok" } });
      await env.run("open(1)");
      await env.click("share");
      const on = snap();
      await env.click("unshare");
      return { on, off: snap() };
    """)
    assert got["on"]["label"] == "Shared"
    assert got["on"]["panelHidden"] is False
    assert got["on"]["expanded"] == "true"
    assert got["on"]["url"] == "http://h/s/tok"
    assert got["on"]["selected"] is True
    assert got["on"]["error"] == ""
    assert got["off"]["label"] == "Share"
    assert got["off"]["panelHidden"] is True
    assert got["off"]["expanded"] == "false"
    assert got["off"]["token"] is None
    assert got["off"]["error"] == ""


@needs_node
def test_failed_turn_off_shows_an_error_and_stays_on(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1, { share_token: "tok" });
      env.handlers["DELETE /api/pages/1/share"] = () => ({ status: 500, body: { detail: "boom" } });
      await env.run("open(1)");
      await env.click("share"); // open the panel
      await env.click("unshare");
      return snap();
    """)
    assert got["error"] == "Couldn't turn off the link. It is still on."
    assert got["token"] == "tok"
    assert got["label"] == "Shared"
    assert got["panelHidden"] is False
    assert got["expanded"] == "true"
    assert got["disabled"] is False


@needs_node
def test_share_error_is_cleared_by_the_next_attempt_and_by_page_changes(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1); env.addPage(2);
      env.handlers["POST /api/pages/1/share"] = () => ({ status: 500, body: {} });
      await env.run("open(1)");
      await env.click("share");
      const failed = snap().error;
      env.handlers["POST /api/pages/1/share"] = () => ({ status: 200, body: { token: "tok" } });
      await env.click("share");
      const retried = snap().error;
      env.handlers["POST /api/pages/1/share"] = () => ({ status: 500, body: {} });
      env.pages[1].share_token = null;
      env.run("current.share_token = null");
      await env.click("share");
      const again = snap().error;
      await env.run("open(2)");
      const afterOpen = snap().error;
      env.handlers["POST /api/pages/2/share"] = () => ({ status: 500, body: {} });
      await env.click("share");
      const failedOn2 = snap().error;
      await env.click("delete");
      return { failed, retried, again, afterOpen, failedOn2, afterDelete: snap().error };
    """)
    assert got["failed"] != ""
    assert got["retried"] == ""
    assert got["again"] != ""
    assert got["afterOpen"] == ""
    assert got["failedOn2"] != ""
    assert got["afterDelete"] == ""


@needs_node
def test_copy_success_says_copied_for_a_moment(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1, { share_token: "tok" });
      const copied = [];
      env.clipboard.writeText = async (t) => { copied.push(t); };
      await env.run("open(1)");
      await env.click("copy");
      const during = snap();
      const timer = env.timers[env.timers.length - 1];
      timer.fn();
      return { during, ms: timer.ms, after: snap().copy, copied };
    """)
    assert got["during"]["copy"] == "Copied"
    assert got["during"]["error"] == ""
    assert got["ms"] == 1500
    assert got["after"] == "Copy link"
    assert got["copied"] == ["http://h/s/tok"]


@needs_node
def test_copy_error_is_cleared_by_the_next_copy(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1, { share_token: "tok" });
      env.clipboard.writeText = async () => { throw new Error("denied"); };
      env.execCommand = () => false;
      await env.run("open(1)");
      await env.click("copy");
      const failed = snap().error;
      env.clipboard.writeText = async () => {};
      await env.click("copy");
      return { failed, error: snap().error, copy: snap().copy };
    """)
    assert got["failed"] != ""
    assert got["error"] == ""
    assert got["copy"] == "Copied"


@needs_node
@pytest.mark.parametrize(
    ("clipboard", "exec_command", "copied"),
    [
        ("async () => { throw new Error('denied'); }", "() => false", False),
        ("async () => { throw new Error('denied'); }", "() => { throw new Error('x'); }", False),
        ("async () => { throw new Error('denied'); }", "() => undefined", False),
        ("async () => { throw new Error('denied'); }", "() => true", True),
    ],
)
def test_copy_falls_back_and_only_says_copied_when_it_worked(
        tmp_path, clipboard, exec_command, copied):
    got = run_editor(tmp_path, snapshot() + f"""
      env.addPage(1, {{ share_token: "tok" }});
      env.clipboard.writeText = {clipboard};
      env.execCommand = {exec_command};
      await env.run("open(1)");
      await env.click("copy");
      return snap();
    """)
    assert got["selected"] is True  # the link is left selected for a manual copy
    if copied:
        assert got["copy"] == "Copied"
        assert got["error"] == ""
    else:
        assert got["copy"] == "Copy link"
        assert got["error"] == (
            "Couldn't copy the link. It is selected: press Ctrl+C (Cmd+C on a Mac).")


@needs_node
def test_aria_expanded_follows_the_panel(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1, { share_token: "tok" }); env.addPage(2, { share_token: "two" });
      env.pages[3] = { ...env.pages[1], id: 3 };
      const seen = [];
      const note = () => { const s = snap(); seen.push([s.expanded, s.panelHidden]); };
      await env.run("open(1)"); note();       // closed
      await env.click("share"); note();       // opened
      await env.click("share"); note();       // closed again
      await env.click("share"); note();       // opened
      await env.run("open(2)"); note();       // another page: closed
      await env.click("share"); note();       // opened
      env.handlers["DELETE /api/pages/2"] = () => ({ status: 204, body: null });
      await env.click("delete"); note();      // page deleted: closed
      return seen;
    """)
    assert got == [
        ["false", True], ["true", False], ["false", True], ["true", False],
        ["false", True], ["true", False], ["false", True],
    ]


@needs_node
def test_in_flight_lock_follows_the_page_not_the_button(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1); env.addPage(2);
      const a = env.deferred(), b = env.deferred();
      env.handlers["POST /api/pages/1/share"] = () => a.promise;
      env.handlers["POST /api/pages/2/share"] = () => b.promise;
      const out = {};
      await env.run("open(1)");
      const startA = env.click("share");
      await env.tick();
      out.aBusy = [snap().disabled, snap().unshareDisabled];
      await env.run("open(2)");
      out.bAfterSwitch = [snap().disabled, snap().unshareDisabled];
      await env.run("open(1)");
      out.aAgain = snap().disabled;
      await env.run("open(2)");
      const startB = env.click("share");       // B has its own request now
      await env.tick();
      out.bBusy = snap().disabled;
      a.resolve({ status: 200, body: { token: "ta" } });
      await startA;
      out.bWhileAFinishes = snap().disabled;   // A ending must not unlock B
      out.bShownAsOff = [snap().label, snap().panelHidden, snap().error];
      b.resolve({ status: 500, body: {} });
      await startB;
      out.bEnd = [snap().disabled, snap().error];
      await env.run("open(1)");
      out.aEnd = [snap().disabled];
      return out;
    """)
    assert got["aBusy"] == [True, True]
    assert got["bAfterSwitch"] == [False, False]
    assert got["aAgain"] is True
    assert got["bBusy"] is True
    assert got["bWhileAFinishes"] is True
    assert got["bShownAsOff"] == ["Share", True, ""]  # A's success does not open B's panel
    assert got["bEnd"][0] is False
    assert got["bEnd"][1] == "Couldn't turn on the link. Try again."
    assert got["aEnd"] == [False]


@needs_node
def test_failure_for_a_page_we_left_is_swallowed(tmp_path):
    got = run_editor(tmp_path, snapshot() + """
      env.addPage(1); env.addPage(2);
      const a = env.deferred();
      env.handlers["POST /api/pages/1/share"] = () => a.promise;
      await env.run("open(1)");
      const startA = env.click("share");
      await env.tick();
      await env.run("open(2)");
      a.resolve({ status: 500, body: {} });
      await startA;
      return snap();
    """)
    assert got["error"] == ""
    assert got["label"] == "Share"
