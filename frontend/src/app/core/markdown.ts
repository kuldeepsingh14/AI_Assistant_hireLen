/**
 * Minimal markdown -> HTML for model output.
 *
 * The model returns light markdown (bullets, bold, inline code). Pulling in a
 * full parser would mean trusting it not to emit script-bearing HTML, so this
 * escapes everything first and then re-introduces only the handful of tags we
 * actually want. Nothing the model writes can become executable markup.
 */

const ESCAPES: Record<string, string> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/** Inline spans, applied to already-escaped text. */
function inline(text: string): string {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
}

export function renderMarkdown(raw: string): string {
  const lines = escapeHtml(raw.trim()).split('\n');
  const html: string[] = [];
  let list: 'ul' | 'ol' | null = null;

  const closeList = () => {
    if (list) {
      html.push(`</${list}>`);
      list = null;
    }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (!trimmed) {
      closeList();
      continue;
    }

    const bullet = trimmed.match(/^[-*]\s+(.*)$/);
    if (bullet) {
      if (list !== 'ul') {
        closeList();
        html.push('<ul>');
        list = 'ul';
      }
      html.push(`<li>${inline(bullet[1])}</li>`);
      continue;
    }

    const numbered = trimmed.match(/^\d+[.)]\s+(.*)$/);
    if (numbered) {
      if (list !== 'ol') {
        closeList();
        html.push('<ol>');
        list = 'ol';
      }
      html.push(`<li>${inline(numbered[1])}</li>`);
      continue;
    }

    const heading = trimmed.match(/^#{1,4}\s+(.*)$/);
    if (heading) {
      closeList();
      html.push(`<h4>${inline(heading[1])}</h4>`);
      continue;
    }

    closeList();
    html.push(`<p>${inline(trimmed)}</p>`);
  }

  closeList();
  return html.join('');
}
