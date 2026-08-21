export function humanFieldLabel(fieldName: string) {
  const action = /^(?:action_item:|action_items\[)(\d+)\]?$/.exec(fieldName)
  if (action) return `Action item ${Number(action[1]) + 1}`
  const requirement = /^(?:requirement:|requirements\[)(\d+)\]?$/.exec(
    fieldName,
  )
  if (requirement) return `Requirement ${Number(requirement[1]) + 1}`
  const normalized = fieldName
    .replaceAll('_', ' ')
    .replace(/\[(\d+)\]/g, (_, index: string) => ` ${Number(index) + 1}`)
    .replace(/:(\d+)/g, (_, index: string) => ` ${Number(index) + 1}`)
    .replace(/\s+/g, ' ')
    .trim()
  return normalized
    ? normalized.charAt(0).toUpperCase() + normalized.slice(1)
    : 'Field'
}

export function evidenceSourceLabel(
  sourceType: string,
  attachmentFilename?: string | null,
) {
  if (sourceType === 'EMAIL' || sourceType === 'EMAIL_BODY') return 'Email body'
  if (sourceType === 'PDF' && attachmentFilename) return attachmentFilename
  return sourceType
    .replaceAll('_', ' ')
    .toLowerCase()
    .replace(/^\w/, (letter) => letter.toUpperCase())
}
