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
  who.textContent = c.author + " · " + when(c.created_at);
  const del = document.createElement("button");
  del.type = "button";
  del.className = "link";
  del.textContent = "Delete";
  del.onclick = async () => {
    if (!current || del.disabled) return;
    del.disabled = true;
    try {
      await api("DELETE", "/api/comments/" + c.id);
      await loadComments();
    } catch (e) {
      showCommentError(e);
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
  const box = document.createElement("textarea");
  box.placeholder = "Reply…";
  box.rows = 2;
  const send = document.createElement("button");
  send.type = "submit";
  send.textContent = "Reply";
  form.append(box, send);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    once(form, async () => {
      const body = box.value;
      if (!body.trim() || !current) return;
      const author = $("author").value.trim();
      setAuthor(author);
      try {
        await api("POST", "/api/comments/" + t.id + "/replies", { body, author });
      } catch (err) {
        showCommentError(err);
        return;
      }
      await loadComments();
    });
  });
  return form;
}

function resolveButton(t) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "resolve";
  btn.textContent = t.resolved ? "Reopen" : "Resolve ✓";
  btn.onclick = async () => {
    if (!current || btn.disabled) return;
    btn.disabled = true;
    try {
      await api("PATCH", "/api/comments/" + t.id, { resolved: !t.resolved });
      await loadComments();
    } catch (e) {
      showCommentError(e);
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
  $("threads").replaceChildren();
  $("resolved-threads").replaceChildren();
  $("resolved").hidden = true;
  $("comments-error").hidden = true;
  $("comment-count").hidden = true; // never show the previous page's count
}

async function loadComments() {
  const pageId = current && current.id;
  if (!pageId) return;
  let data;
  try {
    data = await api("GET", "/api/pages/" + pageId + "/comments");
  } catch (e) {
    if (current && current.id === pageId) showCommentError(e);
    return;
  }
  if (!current || current.id !== pageId) return; // we have left that page
  const openThreads = data.threads.filter((t) => !t.resolved);
  const done = data.threads.filter((t) => t.resolved);
  $("threads").replaceChildren(...openThreads.map(threadEl));
  $("resolved-threads").replaceChildren(...done.map(threadEl));
  $("resolved-summary").textContent = done.length + " resolved";
  $("resolved").hidden = done.length === 0;
  // the loaded thread list is the only source of the count
  $("comment-count").textContent = "💬 " + openThreads.length;
  $("comment-count").hidden = openThreads.length === 0;
  $("comments-error").hidden = true;
}

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
    try {
      await api("POST", "/api/pages/" + current.id + "/comments", { body, author });
    } catch (err) {
      showCommentError(err);
      return;
    }
    // keep anything typed while the post was in flight
    if ($("comment-body").value === body) $("comment-body").value = "";
    await loadComments();
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
