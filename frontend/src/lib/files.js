import { bytes } from './format.js'

const MB = 1024 * 1024
const RULES = {
  image: { max: 8 * MB, types: ['image/png', 'image/jpeg', 'image/webp', 'image/gif'], exts: ['png', 'jpg', 'jpeg', 'webp', 'gif'], label: 'PNG, JPEG, WebP or GIF image' },
  document: {
    max: 20 * MB,
    types: ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    exts: ['pdf', 'docx'], label: 'PDF or DOCX document',
  },
}
export const IMAGE_ACCEPT = RULES.image.types.join(',')
export const DOC_ACCEPT = '.pdf,.docx,' + RULES.document.types.join(',')

const ext = (name) => (name.split('.').pop() || '').toLowerCase()

export function classifyFile(file) {
  for (const kind of ['image', 'document']) {
    const r = RULES[kind]
    if (r.types.includes(file.type) || r.exts.includes(ext(file.name))) return kind
  }
  return null
}

/** Returns a friendly error string, or null when the file is acceptable for `kind`. */
export function validateFile(file, kind) {
  const rule = RULES[kind]
  if (classifyFile(file) !== kind) return `“${file.name}” isn’t supported here. Please choose a ${rule.label}.`
  if (file.size === 0) return `“${file.name}” is empty.`
  if (file.size > rule.max) return `“${file.name}” is ${bytes(file.size)} — the limit is ${bytes(rule.max)}.`
  return null
}
