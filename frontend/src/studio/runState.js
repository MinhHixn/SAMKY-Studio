export const DEFAULT_ROUNDS = 60
export const PREPARATION_STAGES = ['reading','generating_profiles','generating_config','copying_scripts']
export function remainingSeconds(done, total, elapsedSeconds, firstDone = 0) {
  const completed = Number(done) - Number(firstDone)
  const remaining = Number(total) - Number(done)
  if (!Number.isFinite(completed) || !Number.isFinite(remaining) || completed < 2 || remaining <= 0 || elapsedSeconds < 20) return null
  return Math.ceil(remaining * elapsedSeconds / completed)
}
export function runProgress(data, platform = 'parallel') {
  const total = Number(data.total_rounds) || 0
  const rounds = platform === 'parallel' && (data.twitter_current_round != null || data.reddit_current_round != null)
    ? Math.min(Number(data.twitter_current_round) || 0, Number(data.reddit_current_round) || 0)
    : Number(data[`${platform}_current_round`] ?? data.current_round) || 0
  const complete = data.runner_status === 'completed'
  return { total, round:complete ? total : rounds, percent:complete ? 100 : total ? Math.min(99,rounds / total * 100) : null, complete, stopped:data.runner_status === 'stopped', failed:['failed','error'].includes(data.runner_status) }
}
export function saveWorkspace(id, data) { try { sessionStorage.setItem(`sam:run:${id}`,JSON.stringify(data)) } catch { /* Running does not depend on browser storage. */ } }
export function loadWorkspace(id) { try { return JSON.parse(sessionStorage.getItem(`sam:run:${id}`) || '{}') } catch { return {} } }
