// Answers carry [1]-style citation markers (the backend uses them to pick the sources shown under the answer).
// They are not displayed: strip single and grouped markers like [1] or [1, 2] outside fenced code, but keep Markdown
// links such as [text](url) and reference definitions ("[1]: https://…" at the start of a line).
const CITATION = /[^\S\n]*\[\d{1,3}(?:\s*[,;]\s*\d{1,3})*\](?!\()/g

function strip(text) {
  return text.replace(CITATION, (m, offset, s) => {
    const definition = (offset === 0 || s[offset - 1] === '\n') && m === m.trimStart() && s[offset + m.length] === ':'
    return definition ? m : ''
  })
}

export function stripCitations(text) {
  return (text || '')
    .split(/(```[\s\S]*?(?:```|$))/g)
    .map((part, i) => (i % 2 === 1 ? part : strip(part)))
    .join('')
}
