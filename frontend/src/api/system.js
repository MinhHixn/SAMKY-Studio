import service from './index'

export const getSystemStatus = () => service.get('/api/status')
