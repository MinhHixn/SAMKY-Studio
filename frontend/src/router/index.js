import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/StudioHome.vue'

// Load the graph and conversation code only when entering that workspace.
const Simulation = () => import('../views/StudioRun.vue')
const Graph = () => import('../views/StudioGraphPage.vue')
const Report = () => import('../views/StudioReport.vue')
const Interview = () => import('../views/StudioInterview.vue')

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'Home', component: Home },
    { path: '/process/:projectId', name: 'Process', component: Simulation },
    { path: '/simulation/:simulationId', name: 'Simulation', component: Simulation },
    { path: '/simulation/:simulationId/start', name: 'SimulationRun', component: Simulation },
    { path: '/simulation/:simulationId/graph', name: 'SimulationGraph', component: Graph },
    { path: '/simulation/:simulationId/report', name: 'SimulationReport', component: Report },
    { path: '/simulation/:simulationId/interview', name: 'AgentInterview', component: Interview },
    { path: '/report/:reportId', name: 'Report', component: Report },
    { path: '/interaction/:reportId', name: 'Interaction', component: Interview }
  ]
})
