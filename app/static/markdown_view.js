/**
 * Markdownの描画
 *
 * CLIタブのClaudeの応答文を表示するための、必要な範囲の小さな描画処理。
 * 見出し・箇条書き・表・コードブロック・引用・水平線と、強調・コード・リンクの装飾を扱う。
 * 文字列はすべてエスケープしてからタグを組み立てる。
 * 描画したHTMLは、許可したタグ・属性以外を取り除いてから表示する。
 */

// 表示を許可するタグ
const MARKDOWN_ALLOWED_TAGS = new Set([
  "H1", "H2", "H3", "H4", "H5", "H6", "P", "BR", "HR", "UL", "OL", "LI", "BLOCKQUOTE",
  "PRE", "CODE", "STRONG", "EM", "DEL", "A", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "DIV",
]);

// タグごとに許可する属性と、その値の形式
const MARKDOWN_ALLOWED_ATTRS = {
  A: { href: /^https?:\/\//i },
  OL: { start: /^\d+$/ },
  TH: { class: /^md-align-(left|center|right)$/ },
  TD: { class: /^md-align-(left|center|right)$/ },
  DIV: { class: /^md-table-wrap$/ },
};

const MARKDOWN_PATTERNS = {
  fence: /^\s*(`{3,}|~{3,})/,
  heading: /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/,
  hr: /^\s{0,3}([-*_])(\s*\1){2,}\s*$/,
  list: /^(\s*)([-*+]|\d+[.)])\s+(.*)$/,
  quote: /^\s{0,3}>\s?(.*)$/,
  tableSeparator: /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/,
};

/**
 * MarkdownをHTML文字列に変換する
 *
 * 結果は表示前にsanitizeMarkdownHtmlを通すこと。
 */
function renderMarkdown(text) {
  const lines = String(text ?? "").replace(/\u0000/g, "").replace(/\r\n?/g, "\n").split("\n");
  return renderMarkdownBlocks(lines);
}

/**
 * Markdownを描画し、許可したタグ以外を取り除いた要素を返す
 */
function renderMarkdownFragment(text) {
  return sanitizeMarkdownHtml(renderMarkdown(text));
}

/**
 * 行の並びをブロック単位で変換する
 *
 * 先頭から順に、該当するブロックの変換処理を試す。
 */
function renderMarkdownBlocks(lines) {
  const parsers = [parseMarkdownFence, parseMarkdownHeading, parseMarkdownHr, parseMarkdownTable,
    parseMarkdownList, parseMarkdownQuote, parseMarkdownParagraph];
  let html = "";
  let i = 0;
  while (i < lines.length) {
    if (!lines[i].trim()) {
      i += 1;
      continue;
    }
    const block = parsers.map((parse) => parse(lines, i)).find((result) => result);
    html += block.html;
    i = block.next;
  }
  return html;
}

/**
 * コードブロック（```または~~~で囲んだ範囲）
 *
 * 閉じる記号が無い場合は末尾までをコードとする。
 */
function parseMarkdownFence(lines, start) {
  const match = lines[start].match(MARKDOWN_PATTERNS.fence);
  if (!match) return null;
  const marker = match[1];
  const end = lines.findIndex((line, index) => index > start && line.trim().startsWith(marker));
  const close = end < 0 ? lines.length : end;
  const code = lines.slice(start + 1, close).join("\n");
  return { html: `<pre><code>${escapeMarkdownHtml(code)}</code></pre>`, next: close + 1 };
}

function parseMarkdownHeading(lines, start) {
  const match = lines[start].match(MARKDOWN_PATTERNS.heading);
  if (!match) return null;
  const level = match[1].length;
  return { html: `<h${level}>${renderMarkdownInline(match[2])}</h${level}>`, next: start + 1 };
}

function parseMarkdownHr(lines, start) {
  return MARKDOWN_PATTERNS.hr.test(lines[start]) ? { html: "<hr>", next: start + 1 } : null;
}

/**
 * 表（見出し行・区切り行・本文行）
 *
 * 区切り行の「:」の位置で列の寄せ方を決める。
 * 横に長い表は枠の中で横スクロールさせる。
 */
function parseMarkdownTable(lines, start) {
  if (!isMarkdownTableStart(lines, start)) return null;
  const aligns = splitMarkdownTableRow(lines[start + 1]).map(markdownTableAlign);
  const header = renderMarkdownTableRow(splitMarkdownTableRow(lines[start]), aligns, "th");
  let next = start + 2;
  let body = "";
  while (next < lines.length && lines[next].trim() && lines[next].includes("|")) {
    body += renderMarkdownTableRow(splitMarkdownTableRow(lines[next]), aligns, "td");
    next += 1;
  }
  const table = `<table><thead>${header}</thead><tbody>${body}</tbody></table>`;
  return { html: `<div class="md-table-wrap">${table}</div>`, next };
}

function isMarkdownTableStart(lines, start) {
  const separator = lines[start + 1];
  return lines[start].includes("|") && separator !== undefined
    && separator.includes("|") && MARKDOWN_PATTERNS.tableSeparator.test(separator);
}

// 行を「|」で列に分ける（「\|」は列の区切りにしない）
function splitMarkdownTableRow(line) {
  const cells = line.trim().replace(/^\|/, "").replace(/(^|[^\\])\|$/, "$1").split(/(?<!\\)\|/);
  return cells.map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function markdownTableAlign(cell) {
  const left = cell.startsWith(":");
  const right = cell.endsWith(":");
  if (left && right) return "center";
  if (right) return "right";
  return left ? "left" : "";
}

// 見出し行の列数に合わせ、足りない列は空にし余った列は捨てる
function renderMarkdownTableRow(cells, aligns, tag) {
  const html = aligns.map((align, index) => {
    const attr = align ? ` class="md-align-${align}"` : "";
    return `<${tag}${attr}>${renderMarkdownInline(cells[index] ?? "")}</${tag}>`;
  });
  return `<tr>${html.join("")}</tr>`;
}

/**
 * 箇条書き（番号付きを含む）
 *
 * 字下げの深さで入れ子にする。
 * 記号の無い字下げ行は直前の項目の続きとする。
 */
function parseMarkdownList(lines, start) {
  if (!MARKDOWN_PATTERNS.list.test(lines[start]) || MARKDOWN_PATTERNS.hr.test(lines[start])) return null;
  const items = [];
  let next = start;
  while (next < lines.length) {
    const match = lines[next].match(MARKDOWN_PATTERNS.list);
    if (match) items.push({ indent: match[1].length, marker: match[2], text: match[3] });
    else if (/^\s+\S/.test(lines[next])) items[items.length - 1].text += `\n${lines[next].trim()}`;
    else break;
    next += 1;
  }
  return { html: renderMarkdownList(items), next };
}

/**
 * 項目の並びを入れ子のリストに変換する
 *
 * 開いているリストを字下げの深さとともに積んでおき、浅くなったら閉じる。
 */
function renderMarkdownList(items) {
  const stack = [];
  let html = "";
  items.forEach((item) => {
    while (stack.length > 1 && item.indent < stack[stack.length - 1].indent) html += `</li></${stack.pop().tag}>`;
    const top = stack[stack.length - 1];
    if (!top || item.indent > top.indent) {
      const list = openMarkdownList(item);
      stack.push({ indent: item.indent, tag: list.tag });
      html += list.html;
    } else {
      html += "</li>";
    }
    html += `<li>${renderMarkdownInline(item.text)}`;
  });
  return html + stack.reverse().map((list) => `</li></${list.tag}>`).join("");
}

// 番号付きは最初の番号から始める（コードブロックを挟んで続く番号を保つ）
function openMarkdownList(item) {
  const number = item.marker.match(/^\d+/);
  if (!number) return { tag: "ul", html: "<ul>" };
  const start = Number(number[0]);
  return { tag: "ol", html: start === 1 ? "<ol>" : `<ol start="${start}">` };
}

function parseMarkdownQuote(lines, start) {
  if (!MARKDOWN_PATTERNS.quote.test(lines[start])) return null;
  const inner = [];
  let next = start;
  while (next < lines.length && MARKDOWN_PATTERNS.quote.test(lines[next])) {
    inner.push(lines[next].match(MARKDOWN_PATTERNS.quote)[1]);
    next += 1;
  }
  return { html: `<blockquote>${renderMarkdownBlocks(inner)}</blockquote>`, next };
}

/**
 * 段落
 *
 * 空行か、別のブロックの始まりまでを1段落とする。
 */
function parseMarkdownParagraph(lines, start) {
  let next = start + 1;
  while (next < lines.length && lines[next].trim() && !isMarkdownBlockStart(lines, next)) next += 1;
  return { html: `<p>${renderMarkdownInline(lines.slice(start, next).join("\n"))}</p>`, next };
}

function isMarkdownBlockStart(lines, index) {
  const line = lines[index];
  return ["fence", "heading", "hr", "list", "quote"].some((key) => MARKDOWN_PATTERNS[key].test(line))
    || isMarkdownTableStart(lines, index);
}

/**
 * 行内の装飾（コード・リンク・強調・取り消し線）
 *
 * コード部分は装飾しないよう、先に取り出して最後に戻す。
 * 段落内の改行はそのまま改行として表示する（行末の「\」は取り除く）。
 */
function renderMarkdownInline(text) {
  const codes = [];
  const masked = text.replace(/`([^`\n]+)`/g, (_, code) => `\u0000${codes.push(code) - 1}\u0000`);
  const html = escapeMarkdownHtml(masked)
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*(?=\S)(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*\w])\*(?=[^*\s])([^*\n]*?[^*\s])?\*(?!\*)/g, (_, pre, body) => `${pre}<em>${body ?? ""}</em>`)
    .replace(/~~(?=\S)(.+?)~~/g, "<del>$1</del>")
    .replace(/(?: {2,}|\\)?\n/g, "<br>")
    .replace(/\\$/, "");
  return html.replace(/\u0000(\d+)\u0000/g, (_, index) => `<code>${escapeMarkdownHtml(codes[index])}</code>`);
}

function escapeMarkdownHtml(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/**
 * 許可したタグ・属性以外を取り除く（XSS対策）
 *
 * templateに入れた要素はスクリプトも画像読み込みも実行されない。
 * 許可しないタグは文字列に置き換え、許可しない属性は削除する。
 */
function sanitizeMarkdownHtml(html) {
  const template = document.createElement("template");
  template.innerHTML = html;
  sanitizeMarkdownChildren(template.content);
  return template.content;
}

function sanitizeMarkdownChildren(parent) {
  Array.from(parent.childNodes).forEach((node) => {
    if (node.nodeType === Node.TEXT_NODE) return;
    if (node.nodeType !== Node.ELEMENT_NODE) {
      node.remove();
      return;
    }
    if (!MARKDOWN_ALLOWED_TAGS.has(node.tagName)) {
      node.replaceWith(document.createTextNode(node.textContent));
      return;
    }
    sanitizeMarkdownAttributes(node);
    sanitizeMarkdownChildren(node);
  });
}

// リンクは別タブで開き、遷移元の情報を渡さない
function sanitizeMarkdownAttributes(element) {
  const allowed = MARKDOWN_ALLOWED_ATTRS[element.tagName] || {};
  Array.from(element.attributes)
    .filter((attr) => !allowed[attr.name] || !allowed[attr.name].test(attr.value))
    .forEach((attr) => element.removeAttribute(attr.name));
  if (element.tagName !== "A") return;
  element.setAttribute("target", "_blank");
  element.setAttribute("rel", "noopener noreferrer");
}
