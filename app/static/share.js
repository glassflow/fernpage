(function () {
  const token = location.pathname.split("/").filter(Boolean).pop() || "";

  function showDead() {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "This link doesn't work. It may have been turned off.";
    document.querySelector("main").replaceChildren(p);
  }

  function show(page) {
    const title = page.title || "Untitled";
    document.getElementById("title").textContent = title;
    document.title = title + " · Fernpage";
    document.getElementById("icon").textContent = page.icon || "📄";
    const view = document.getElementById("view");
    view.innerHTML = window.renderMarkdown(page.body);
    view.querySelectorAll("input[type=checkbox]").forEach((box) => {
      box.disabled = true;
    });
    document.getElementById("updated").textContent =
      "Shared from Fernpage · Edited " + new Date(page.updated_at).toLocaleString();
  }

  fetch("/api/shared/" + encodeURIComponent(token))
    .then((res) => (res.ok ? res.json() : null))
    .then((page) => (page ? show(page) : showDead()))
    .catch(showDead);
})();
