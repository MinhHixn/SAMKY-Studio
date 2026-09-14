import { test } from 'node:test'
import assert from 'node:assert/strict'
import { runProgress, DEFAULT_ROUNDS, remainingSeconds } from '../src/studio/runState.js'

test('the initial recommendation is 60 rounds', () => assert.equal(DEFAULT_ROUNDS,60))
test('parallel progress follows the slower enabled community', () => {
  const state=runProgress({runner_status:'running',total_rounds:60,twitter_current_round:40,reddit_current_round:24})
  assert.equal(state.round,24);assert.equal(state.percent,40)
})
test('a single platform is not held at zero by a disabled community', () => {
  assert.equal(runProgress({runner_status:'running',total_rounds:60,reddit_current_round:30,twitter_current_round:0},'reddit').percent,50)
})
test('stopped runs are not presented as complete', () => {
  const state=runProgress({runner_status:'stopped',total_rounds:60,current_round:12},'reddit')
  assert.equal(state.stopped,true);assert.equal(state.complete,false);assert.equal(state.percent,20)
})
test('100 percent requires completion, and unknown duration stays indeterminate', () => {
  assert.equal(runProgress({runner_status:'running',total_rounds:60,current_round:60},'reddit').percent,99)
  assert.equal(runProgress({runner_status:'completed',total_rounds:60,current_round:60},'reddit').percent,100)
  assert.equal(runProgress({runner_status:'starting'},'reddit').percent,null)
})
test('remaining time needs observed work and never claims stalled work is complete', () => {
  assert.equal(remainingSeconds(1,60,60),null)
  assert.equal(remainingSeconds(12,60,600),2400)
  assert.equal(remainingSeconds(7,7,90),null)
  assert.equal(remainingSeconds(5,7,45,4),null)
})
