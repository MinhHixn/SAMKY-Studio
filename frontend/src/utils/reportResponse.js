// Accept both the current API contract and older servers still wrapping results.
export const getReportReply = (data) => {
  const result = data?.response
  const text = typeof result === 'string'
    ? result
    : result?.response ?? data?.answer
  if (typeof text !== 'string' || !text.trim()) {
    throw new Error('Report Agent returned an empty or invalid reply. Please try again.')
  }
  return text
}
