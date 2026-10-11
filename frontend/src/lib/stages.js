export const STAGES = [
  { key: 'understanding', label: 'Understanding question…' },
  { key: 'retrieving', label: 'Retrieving documentation…' },
  { key: 'reranking', label: 'Ranking sources…' },
  { key: 'generating', label: 'Generating answer…' },
]
const OTHER = { uploading: 'Uploading image…', analyzing: 'Analyzing image…' }

export function stageLabel(stage, serverLabel) {
  if (serverLabel) return serverLabel
  if (OTHER[stage]) return OTHER[stage]
  const s = STAGES.find((x) => x.key === stage)
  return s ? s.label : 'Working…'
}
