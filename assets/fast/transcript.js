'use strict';

// Load the local lexer only when there is a transcript. Convert tokens to DOM
// nodes instead of inserting generated HTML (including during streaming).
let lexerLoading;
function loadLexer() {
  if (!lexerLoading) {
    const script = document.createElement('script');
    script.src = '/_styx/fast/marked-18.1.0.js';
    script.integrity = '__MARKED_INTEGRITY__';
    lexerLoading = new Promise((resolve, reject) => {
      script.onload = resolve;
      script.onerror = () => { lexerLoading = null; script.remove(); reject(new Error()); };
      document.head.append(script);
    });
  }
  return lexerLoading;
}

function markdownNodes(tokens) {
  const fragment = document.createDocumentFragment();
  for (const t of tokens) {
    let el;
    switch (t.type) {
      case 'space': continue;
      case 'hr': case 'br': el = node(t.type); break;
      case 'heading': el = node(`h${t.depth}`); break;
      case 'paragraph': el = node('p'); break;
      case 'blockquote': case 'strong': case 'em': case 'del': el = node(t.type); break;
      case 'escape': case 'html': fragment.append(t.text ?? t.raw); continue;
      case 'text':
        fragment.append(t.tokens ? markdownNodes(t.tokens) : t.text);
        continue;
      case 'codespan': el = node('code', t.text); break;
      case 'code':
        el = node('pre'); el.append(node('code', t.text)); break;
      case 'list':
        el = node(t.ordered ? 'ol' : 'ul');
        if (t.ordered) el.start = t.start;
        for (const item of t.items) {
          const li = node('li');
          if (item.task) li.append(item.checked ? '☑ ' : '☐ ');
          li.append(markdownNodes(item.tokens)); el.append(li);
        }
        break;
      case 'table': {
        el = node('div', '', 'table-scroll');
        const table = node('table');
        for (const [section, rows, tag] of [['thead', [t.header], 'th'], ['tbody', t.rows, 'td']]) {
          const group = node(section);
          for (const row of rows) {
            const tr = node('tr');
            for (const cell of row) {
              const col = node(tag);
              col.append(markdownNodes(cell.tokens)); tr.append(col);
            }
            group.append(tr);
          }
          table.append(group);
        }
        el.append(table); break;
      }
      case 'link':
        el = node('span');
        try {
          const url = new URL(t.href);
          if (['https:', 'http:'].includes(url.protocol)) {
            el = node('a'); el.href = url.href; el.target = '_blank'; el.rel = 'noopener noreferrer';
          }
        } catch {}
        break;
      case 'image': fragment.append(t.text || '[image]'); continue;
      default: fragment.append(t.raw || ''); continue;
    }
    if (t.tokens) el.append(markdownNodes(t.tokens));
    fragment.append(el);
  }
  return fragment;
}

function renderReply(el, source) {
  function paint() {
    try { el.replaceChildren(markdownNodes(marked.lexer(source))); }
    catch { el.textContent = source; }
  }
  if (window.marked) { paint(); return; }
  el.textContent = source;
  loadLexer().then(() => {
    if (el.isConnected && el.textContent === source) {
      const follow = atBottom();
      paint();
      if (follow) bottom();
    }
  }).catch(() => {});
}
