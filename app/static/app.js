const $ = (id) => document.getElementById(id);
const ICONS = ["📄", "🌱", "📘", "🧭", "🗺️", "🗓️", "☕", "✅", "💡", "🧪", "🎯", "📌"];

let pages = [];        // the tree from the server
let current = null;    // the open page
let saveTimer = null;

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "content-type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.status === 204 ? null : res.json();
}

function flatten(nodes, out = []) {
  nodes.forEach((n) => { out.push(n); flatten(n.children, out); });
  return out;
}

function trail(id) {
  const byId = Object.fromEntries(flatten(pages).map((p) => [p.id, p]));
  const chain = [];
  for (let p = byId[id]; p; p = byId[p.parent_id]) chain.unshift(p);
  return chain;
}

// ── sidebar ──
async function loadTree() {
  const data = await api("GET", "/api/pages");
  pages = data.pages;
  $("tree").replaceChildren(...pages.map(treeItem));
  $("favorites").replaceChildren(...data.favorites.map((f) => linkItem(f)));
  $("favorites-section").hidden = data.favorites.length === 0;
}

function linkItem(page) {
  const li = document.createElement("li");
  const a = document.createElement("a");
  a.href = "#" + page.id;
  a.textContent = `${page.icon || "📄"} ${page.title || "Untitled"}`;
  if (current && current.id === page.id) a.classList.add("active");
  li.append(a);
  return li;
}

function treeItem(node) {
  const li = linkItem(node);
  const add = document.createElement("button");
  add.className = "add";
  add.title = "Add a page inside";
  add.textContent = "+";
  add.onclick = () => newPage(node.id);
  li.firstChild.after(add);
  if (node.children.length) {
    const ul = document.createElement("ul");
    ul.append(...node.children.map(treeItem));
    li.append(ul);
  }
  return li;
}

// ── page ──
async function open(id) {
  clearComments();
  try {
    current = await api("GET", "/api/pages/" + id);
  } catch {
    current = null;
  }
  $("empty").hidden = !!current;
  $("page").hidden = !current;
  if (!current) return loadTree();
  $("title").value = current.title;
  $("icon").textContent = current.icon || "📄";
  $("body").value = current.body;
  $("favorite").textContent = current.favorite ? "★" : "☆";
  $("favorite").classList.toggle("on", current.favorite);
  $("saved").textContent = "Edited " + new Date(current.updated_at).toLocaleString();
  $("share-panel").hidden = true;
  showShare();
  $("crumbs").replaceChildren(...trail(current.id).slice(0, -1).flatMap((p) => {
    const a = document.createElement("a");
    a.href = "#" + p.id;
    a.textContent = `${p.icon || "📄"} ${p.title || "Untitled"}`;
    const sep = document.createElement("span");
    sep.textContent = " / ";
    return [a, sep];
  }));
  setMode(current.body.trim() ? "read" : "write");
  clearComments(); // again: a late load for the page we just left may have filled the lists
  loadComments();
  await loadTree();
}

function setMode(mode) {
  const writing = mode === "write";
  $("body").hidden = !writing;
  $("view").hidden = writing;
  $("mode").textContent = writing ? "Done" : "Edit";
  if (writing) $("body").focus();
  else $("view").innerHTML = window.renderMarkdown(current.body);
}

function save(changes) {
  Object.assign(current, changes);
  $("saved").textContent = "Saving…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const page = await api("PATCH", "/api/pages/" + current.id, changes);
    $("saved").textContent = "Saved";
    current.updated_at = page.updated_at;
    if ("title" in changes || "icon" in changes || "favorite" in changes) loadTree();
  }, 400);
}

async function newPage(parentId = null) {
  const page = await api("POST", "/api/pages", { title: "", parent_id: parentId });
  location.hash = page.id;
  await open(page.id);
  setMode("write");
  $("title").focus();
}

// ── comments ──
const AUTHOR_KEY = "fernpage.author";

function getAuthor() {
  try { return localStorage.getItem(AUTHOR_KEY) || ""; } catch { return ""; }
}

function setAuthor(name) {
  try { localStorage.setItem(AUTHOR_KEY, name); } catch { /* storage unavailable */ }
}

function when(iso) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// unsent reply text by thread id, so a re-render (resolve, delete, a reply elsewhere) keeps it
const drafts = new Map();

// which comment control has focus, so it can be given back after the lists are rebuilt
function focusSnapshot() {
  const el = document.activeElement;
  if (!el || !el.dataset || !el.dataset.focus || !$("comments").contains(el)) return null;
  const snap = { key: el.dataset.focus.replace(/^reply-send-/, "reply-") };
  if (el.tagName === "TEXTAREA") { snap.start = el.selectionStart; snap.end = el.selectionEnd; }
  return snap;
}

function restoreFocus(snap) {
  if (!snap) return;
  const el = [...$("comments").querySelectorAll("[data-focus]")]
    .find((x) => x.dataset.focus === snap.key);
  if (!el) { $("comments").focus({ preventScroll: true }); return; } // e.g. the comment is gone
  el.focus({ preventScroll: true });
  // a control inside the closed "resolved" fold cannot take focus: park it on the section
  if (document.activeElement !== el) { $("comments").focus({ preventScroll: true }); return; }
  if (snap.start != null) el.setSelectionRange(snap.start, snap.end);
}

// Run one comment action, then always reload the list: after a failure too, because the screen
// may be stale (a 404 after a delete in another tab). The error shows only on the page it is for.
async function act(work, snap = focusSnapshot()) {
  const pageId = current && current.id;
  if (!pageId) return false;
  let failure = null;
  try {
    await work();
  } catch (e) {
    failure = e;
  }
  await loadComments(snap);
  if (failure && current && current.id === pageId) showCommentError(failure);
  return !failure;
}

function commentBody(text) {
  const div = document.createElement("div");
  div.className = "comment-body markdown";
  div.innerHTML = window.renderMarkdown(text);
  div.querySelectorAll("input[type=checkbox]").forEach((box) => { box.disabled = true; });
  return div;
}

function commentEl(c) {
  const div = document.createElement("div");
  div.className = "comment";
  div.dataset.id = c.id;
  const meta = document.createElement("div");
  meta.className = "meta";
  const who = document.createElement("span");
  who.id = "who-" + c.id;
  who.textContent = c.author + " · " + when(c.created_at);
  const del = document.createElement("button");
  del.type = "button";
  del.className = "link";
  del.id = "del-" + c.id;
  del.dataset.focus = "delete-" + c.id;
  // name = "Delete" + who and when, read from the span above (no user text goes into an attribute)
  del.setAttribute("aria-labelledby", del.id + " " + who.id);
  del.textContent = "Delete";
  del.onclick = async () => {
    if (!current || del.disabled) return;
    const snap = focusSnapshot();
    del.disabled = true;
    try {
      await act(async () => { await api("DELETE", "/api/comments/" + c.id); }, snap);
    } finally {
      del.disabled = false;
    }
  };
  meta.append(who, del);
  div.append(meta, commentBody(c.body));
  return div;
}

// run work() for a form once at a time: a second click or Ctrl+Enter while it runs does nothing
async function once(form, work) {
  if (form.dataset.busy) return;
  form.dataset.busy = "1";
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  try {
    await work();
  } finally {
    delete form.dataset.busy;
    button.disabled = false;
  }
}

function replyForm(t) {
  const form = document.createElement("form");
  form.className = "reply-form";
  const hint = document.createElement("span");
  hint.className = "sr-only";
  hint.id = "reply-lbl-" + t.id;
  hint.textContent = "Reply to";
  const box = document.createElement("textarea");
  box.placeholder = "Reply…";
  box.rows = 2;
  box.dataset.focus = "reply-" + t.id;
  box.setAttribute("aria-labelledby", hint.id + " who-" + t.id); // "Reply to <author · date>"
  box.value = drafts.get(t.id) || ""; // an unsent draft survives a re-render
  box.addEventListener("input", () => {
    if (box.value) drafts.set(t.id, box.value);
    else drafts.delete(t.id);
  });
  const send = document.createElement("button");
  send.type = "submit";
  send.dataset.focus = "reply-send-" + t.id;
  send.textContent = "Reply";
  form.append(hint, box, send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const snap = focusSnapshot();
    once(form, async () => {
      const body = box.value;
      if (!body.trim() || !current) return;
      const author = $("author").value.trim();
      setAuthor(author);
      await act(async () => {
        await api("POST", "/api/comments/" + t.id + "/replies", { body, author });
        // sent: forget the draft, unless more was typed meanwhile
        if (box.value === body) drafts.delete(t.id);
      }, snap);
    });
  });
  return form;
}

function resolveButton(t) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "resolve";
  btn.dataset.focus = "resolve-" + t.id;
  btn.textContent = t.resolved ? "Reopen" : "Resolve ✓";
  btn.setAttribute("aria-label", t.resolved ? "Reopen thread" : "Resolve thread");
  btn.onclick = async () => {
    if (!current || btn.disabled) return;
    const snap = focusSnapshot();
    btn.disabled = true;
    try {
      await act(async () => {
        await api("PATCH", "/api/comments/" + t.id, { resolved: !t.resolved });
      }, snap);
    } finally {
      btn.disabled = false;
    }
  };
  return btn;
}

function threadEl(t) {
  const div = document.createElement("div");
  div.className = "thread";
  div.dataset.id = t.id;
  const replies = document.createElement("div");
  replies.className = "replies";
  replies.append(...t.replies.map(commentEl));
  div.append(commentEl(t), replies);
  if (!t.resolved) div.append(replyForm(t));
  const foot = document.createElement("div");
  foot.className = "thread-foot";
  foot.append(resolveButton(t));
  div.append(foot);
  return div;
}

function showCommentError(e) {
  const p = $("comments-error");
  p.textContent = "Comments: " + e.message;
  p.hidden = false;
}

function clearComments() {
  loadSeq++; // a load still in flight belongs to the page we are leaving
  drafts.clear();
  $("threads").replaceChildren();
  $("resolved-threads").replaceChildren();
  $("resolved").hidden = true;
  $("comments-error").hidden = true;
  $("comment-count").hidden = true; // never show the previous page's count
}

let loadSeq = 0; // the newest load wins: an older answer for the same page is dropped

async function loadComments(snap = null) {
  const pageId = current && current.id;
  if (!pageId) return false;
  const seq = ++loadSeq;
  let data;
  try {
    data = await api("GET", "/api/pages/" + pageId + "/comments");
  } catch (e) {
    if (seq === loadSeq && current && current.id === pageId) showCommentError(e);
    return false;
  }
  if (seq !== loadSeq || !current || current.id !== pageId) return false; // superseded, or we left
  // focus now if it is on a comment control; if it fell to the page, where it was at the click
  const active = document.activeElement;
  const focus = focusSnapshot() || (active && active !== document.body ? null : snap);
  const openThreads = data.threads.filter((t) => !t.resolved);
  const done = data.threads.filter((t) => t.resolved);
  const ids = new Set(data.threads.map((t) => t.id));
  for (const id of [...drafts.keys()]) if (!ids.has(id)) drafts.delete(id); // thread was deleted
  $("threads").replaceChildren(...openThreads.map(threadEl));
  $("resolved-threads").replaceChildren(...done.map(threadEl));
  $("resolved-summary").textContent = done.length + " resolved";
  $("resolved").hidden = done.length === 0;
  // the loaded thread list is the only source of the count
  $("comment-count").textContent = "💬 " + openThreads.length;
  $("comment-count").setAttribute(
    "aria-label", openThreads.length + (openThreads.length === 1 ? " open comment" : " open comments"));
  $("comment-count").hidden = openThreads.length === 0;
  $("comments-error").hidden = true;
  restoreFocus(focus);
  return true;
}

// ── sharing ──
function shareUrl() { return location.origin + "/s/" + current.share_token; }

function showShare() {
  const on = !!(current && current.share_token);
  $("share").textContent = on ? "Shared" : "Share";
  $("share").classList.toggle("on", on);
  $("share-url").value = on ? shareUrl() : "";
}

// Record a new token on the page the request was for, and on the open page if it is the same
// page (it may have been reloaded meanwhile). Returns true when the open page is that page.
function applyToken(page, token) {
  page.share_token = token;
  if (!current || current.id !== page.id) return false;
  current.share_token = token;
  return true;
}

$("share").onclick = async () => {
  if (!current) return;
  if (current.share_token) {
    $("share-panel").hidden = !$("share-panel").hidden;
    return;
  }
  const page = current;
  const button = $("share");
  if (button.disabled) return;
  button.disabled = true;
  try {
    const res = await api("POST", "/api/pages/" + page.id + "/share");
    if (!applyToken(page, res.token)) return; // we moved to another page: do not show its panel
    showShare();
    $("share-panel").hidden = false;
    $("share-url").select();
  } finally {
    button.disabled = false;
  }
};

$("copy").onclick = async () => {
  if (!current || !current.share_token) return;
  const url = shareUrl();
  try {
    await navigator.clipboard.writeText(url);
  } catch {
    $("share-url").select();
    document.execCommand("copy");
  }
  $("copy").textContent = "Copied";
  setTimeout(() => { $("copy").textContent = "Copy link"; }, 1500);
};

$("unshare").onclick = async () => {
  if (!current) return;
  const page = current;
  const button = $("unshare");
  if (button.disabled) return;
  button.disabled = true;
  try {
    await api("DELETE", "/api/pages/" + page.id + "/share");
    if (!applyToken(page, null)) return;
    $("share-panel").hidden = true;
    showShare();
  } finally {
    button.disabled = false;
  }
};

// ── search ──
let searchTimer = null;
$("search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value;
  searchTimer = setTimeout(async () => {
    const list = $("results");
    if (!q.trim()) { list.hidden = true; return; }
    const { results } = await api("GET", "/api/search?q=" + encodeURIComponent(q));
    list.replaceChildren(...results.map((r) => {
      const li = document.createElement("li");
      li.innerHTML = `<a href="#${r.id}"></a><small></small>`;
      li.firstChild.textContent = `${r.icon || "📄"} ${r.title || "Untitled"}`;
      li.lastChild.textContent = r.snippet;
      return li;
    }));
    if (!results.length) list.innerHTML = "<li class=\"none\">No pages match</li>";
    list.hidden = false;
  }, 150);
});

// ── wiring ──
$("title").addEventListener("input", (e) => save({ title: e.target.value }));
$("body").addEventListener("input", (e) => save({ body: e.target.value }));
$("mode").onclick = () => setMode($("body").hidden ? "write" : "read");
$("favorite").onclick = () => {
  save({ favorite: !current.favorite });
  $("favorite").textContent = current.favorite ? "★" : "☆";
  $("favorite").classList.toggle("on", current.favorite);
};
$("icon").onclick = () => {
  const next = ICONS[(ICONS.indexOf(current.icon) + 1) % ICONS.length];
  $("icon").textContent = next;
  save({ icon: next });
};
$("delete").onclick = async () => {
  await api("DELETE", "/api/pages/" + current.id);
  current = null;
  location.hash = "";
  $("page").hidden = true;
  $("share-panel").hidden = true;
  $("empty").hidden = false;
  loadTree();
};
$("view").addEventListener("change", (e) => {
  // ticking a task box in reading mode updates the markdown line it came from
  const i = Number(e.target.dataset.line);
  const lines = current.body.split("\n");
  lines[i] = lines[i].replace(/\[( |x)\]/i, e.target.checked ? "[x]" : "[ ]");
  save({ body: lines.join("\n") });
  e.target.closest("li").classList.toggle("done", e.target.checked);
});
$("author").value = getAuthor();
$("new-comment").addEventListener("submit", (e) => {
  e.preventDefault();
  once($("new-comment"), async () => {
    const body = $("comment-body").value;
    if (!body.trim() || !current) return;
    const author = $("author").value.trim();
    setAuthor(author);
    await act(async () => {
      await api("POST", "/api/pages/" + current.id + "/comments", { body, author });
      // keep anything typed while the post was in flight
      if ($("comment-body").value === body) $("comment-body").value = "";
    });
  });
});
$("comments").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && e.target.tagName === "TEXTAREA") {
    e.preventDefault();
    e.target.form.requestSubmit();
  }
});
$("comment-count").onclick = () => {
  $("comments").scrollIntoView({ behavior: "smooth", block: "start" });
};
$("new-page").onclick = () => newPage();
window.addEventListener("hashchange", () => {
  const id = Number(location.hash.slice(1));
  if (id && (!current || current.id !== id)) {
    $("results").hidden = true;
    open(id);
  }
});

(async () => {
  await loadTree();
  const id = Number(location.hash.slice(1)) || (pages[0] && pages[0].id);
  if (id) open(id);
})();
