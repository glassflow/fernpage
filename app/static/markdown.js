// A small markdown renderer: headings, paragraphs, lists, task lists, quotes, code, links,
// bold, italics and inline code. Everything is escaped first, so page text can't inject HTML.
(function () {
  function escape(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function inline(s) {
    return escape(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  }

  function render(text) {
    const out = [];
    const lines = text.replace(/\r\n/g, "\n").split("\n");
    let list = null;
    let para = [];
    let code = null;

    const flushPara = () => {
      if (para.length) out.push("<p>" + inline(para.join(" ")) + "</p>");
      para = [];
    };
    const closeList = () => {
      if (list) out.push("</" + list + ">");
      list = null;
    };

    lines.forEach((line, i) => {
      if (code !== null) {
        if (line.startsWith("```")) {
          out.push("<pre><code>" + escape(code.join("\n")) + "</code></pre>");
          code = null;
        } else code.push(line);
        return;
      }
      if (line.startsWith("```")) { flushPara(); closeList(); code = []; return; }

      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      const task = line.match(/^\s*[-*]\s+\[( |x)\]\s+(.*)$/i);
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+\.\s+(.*)$/);
      const quote = line.match(/^>\s?(.*)$/);

      if (heading) {
        flushPara(); closeList();
        const n = heading[1].length + 1;
        out.push(`<h${n}>${inline(heading[2])}</h${n}>`);
      } else if (task || bullet || numbered) {
        flushPara();
        const kind = numbered ? "ol" : "ul";
        if (list !== kind) { closeList(); out.push("<" + kind + ">"); list = kind; }
        if (task) {
          const done = task[1].toLowerCase() === "x";
          out.push(`<li class="task${done ? " done" : ""}"><input type="checkbox" data-line="${i}"${done ? " checked" : ""}> ${inline(task[2])}</li>`);
        } else {
          out.push("<li>" + inline((bullet || numbered)[1]) + "</li>");
        }
      } else if (quote) {
        flushPara(); closeList();
        out.push("<blockquote>" + inline(quote[1]) + "</blockquote>");
      } else if (!line.trim()) {
        flushPara(); closeList();
      } else {
        closeList();
        para.push(line.trim());
      }
    });
    if (code !== null) out.push("<pre><code>" + escape(code.join("\n")) + "</code></pre>");
    flushPara(); closeList();
    return out.join("\n");
  }

  window.renderMarkdown = render;
})();
