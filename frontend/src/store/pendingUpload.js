/**
 * Temporarily store files and requirements to be uploaded
 * Used to immediately navigate after clicking Start Engine on home page, API call is made on Process page
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  projectName: '',
  isPending: false,
  settings: { rounds: 60, platform: 'parallel' }
})

export function setPendingUpload(files, requirement, projectName = '', settings = { rounds: 60, platform: 'parallel' }) {
  state.files = files
  state.simulationRequirement = requirement
  state.projectName = projectName
  state.isPending = true
  state.settings = { ...settings }
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    projectName: state.projectName,
    isPending: state.isPending,
    settings: { ...state.settings }
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.projectName = ''
  state.isPending = false
}

export default state
