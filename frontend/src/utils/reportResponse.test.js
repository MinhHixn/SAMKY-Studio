import test from 'node:test'
import assert from 'node:assert/strict'
import { getReportReply } from './reportResponse.js'

test('renders the current API response as text', () => {
  assert.equal(getReportReply({ response: 'Answer', tool_calls: [] }), 'Answer')
})

test('accepts the older nested response without sending an object to Markdown', () => {
  assert.equal(getReportReply({ response: { response: 'Answer', sources: [] } }), 'Answer')
})

test('rejects empty and invalid responses so the UI can display a retryable error', () => {
  for (const data of [null, {}, { response: {} }, { response: [] }, { response: '  ' }]) {
    assert.throws(() => getReportReply(data), /empty or invalid/)
  }
})
