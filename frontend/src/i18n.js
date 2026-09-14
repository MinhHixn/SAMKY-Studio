import { computed, ref, watch } from 'vue'

const supported = ['en', 'vi', 'es']
const saved = localStorage.getItem('mirofish:locale')
export const locale = ref(supported.includes(saved) ? saved : 'en')

const messages = {
  en: {
    nav: 'Main navigation', home: 'SAMKY Studio home', noUi: 'Headless', github: 'GitHub',
    eyebrow: 'Event simulation workspace', titleA: 'Test a future', titleB: 'before it happens.',
    intro: 'Turn event material into an agent society, observe chain reactions, and surface the scenarios worth paying attention to.',
    environment: 'CURRENT ENVIRONMENT', checking: 'Checking services…', ready: 'Ready to simulate', setup: 'Setup required', refresh: 'Check system again',
    model: 'Model', neo4j: 'Neo4j', mode: 'Mode', online: 'Online', offline: 'Offline', connected: 'Connected', disconnected: 'Not connected',
    bothDown: 'The model service and Neo4j are not responding. Finish setup before starting.', neoDown: 'Neo4j is not responding.', modelDown: 'The model service is not responding.',
    flowLabel: 'Simulation workflow', flow1: 'Read the context', flow1b: 'Documents → knowledge graph', flow2: 'Build the society', flow2b: 'Personas → multi-agent interactions', flow3: 'Surface signals', flow3b: 'Timeline → scenario report',
    newEvent: 'SIMULATION / NEW', create: 'Create an event simulation', privacy: 'Your data, your control',
    eventName: 'Event name', optional: 'Optional', eventPlaceholder: 'Example: Reactions to a new policy announcement',
    question: 'Simulation question', questionPlaceholder: 'What could happen, who will react, and which signals should we watch?',
    sources: 'Context sources', drop: 'Drop PDF, Markdown, or TXT here', browse: 'or click to browse · 50 MB maximum', add: '+ Add documents', remove: 'Remove',
    invalidFile: 'Some files were skipped because their format is unsupported or they exceed 50 MB.', documents: 'documents', nextSetup: 'Configure agents in the next step', launch: 'Start simulation', opening: 'Opening workspace…',
    headlessTitle: 'Prefer automation without a UI?', headlessBody: 'The CLI uses the same SAM pipeline and API.', copy: 'Copy command', copied: 'Copied',
    records: 'Simulation records', graphConstruction: 'Graph construction', envSetup: 'Environment setup', analysisReport: 'Analysis report', filesMore: 'more files', noFiles: 'No files', loading: 'Loading…', simRequirement: 'Simulation question', none: 'None', assocFiles: 'Associated files', noAssoc: 'No associated files', playback: 'Simulation playback', step: 'Step', playbackHint: 'Start Simulation and Deep Interaction are live-only steps and cannot be replayed from history.', unnamed: 'Unnamed simulation', rounds: 'rounds', unknownFile: 'Unknown file'
  },
  vi: {
    nav: 'Điều hướng chính', home: 'SAMKY Studio - trang chủ', noUi: 'Không dùng UI', github: 'GitHub',
    eyebrow: 'Không gian mô phỏng sự kiện', titleA: 'Thử một tương lai', titleB: 'trước khi nó xảy ra.',
    intro: 'Biến tài liệu về sự kiện thành một xã hội tác nhân, quan sát phản ứng dây chuyền và tìm ra những kịch bản đáng chú ý.',
    environment: 'MÔI TRƯỜNG HIỆN TẠI', checking: 'Đang kiểm tra dịch vụ…', ready: 'Sẵn sàng mô phỏng', setup: 'Cần hoàn tất thiết lập', refresh: 'Kiểm tra lại hệ thống',
    model: 'Model', neo4j: 'Neo4j', mode: 'Chế độ', online: 'Online', offline: 'Offline', connected: 'Đã kết nối', disconnected: 'Chưa kết nối',
    bothDown: 'Model và Neo4j chưa phản hồi. Hãy hoàn tất thiết lập trước khi chạy.', neoDown: 'Neo4j chưa phản hồi.', modelDown: 'Dịch vụ model chưa phản hồi.',
    flowLabel: 'Quy trình mô phỏng', flow1: 'Đọc bối cảnh', flow1b: 'Tài liệu → knowledge graph', flow2: 'Tạo xã hội', flow2b: 'Persona → tương tác đa tác nhân', flow3: 'Rút tín hiệu', flow3b: 'Timeline → báo cáo kịch bản',
    newEvent: 'SIMULATION / MỚI', create: 'Tạo simulation cho sự kiện', privacy: 'Dữ liệu thuộc về bạn',
    eventName: 'Tên sự kiện', optional: 'Tùy chọn', eventPlaceholder: 'Ví dụ: Phản ứng sau thông báo chính sách mới',
    question: 'Câu hỏi cần mô phỏng', questionPlaceholder: 'Điều gì có thể xảy ra, ai sẽ phản ứng và tín hiệu nào cần theo dõi?',
    sources: 'Nguồn bối cảnh', drop: 'Thả PDF, Markdown hoặc TXT vào đây', browse: 'hoặc bấm để chọn · tối đa 50 MB', add: '+ Thêm tài liệu', remove: 'Xóa',
    invalidFile: 'Một số tệp bị bỏ qua vì sai định dạng hoặc lớn hơn 50 MB.', documents: 'tài liệu', nextSetup: 'Thiết lập agent ở bước tiếp theo', launch: 'Bắt đầu mô phỏng', opening: 'Đang mở workspace…',
    headlessTitle: 'Muốn chạy tự động, không cần giao diện?', headlessBody: 'CLI dùng cùng pipeline và API của SAM.', copy: 'Sao chép lệnh', copied: 'Đã sao chép',
    records: 'Lịch sử mô phỏng', graphConstruction: 'Dựng knowledge graph', envSetup: 'Thiết lập môi trường', analysisReport: 'Báo cáo phân tích', filesMore: 'tệp khác', noFiles: 'Không có tệp', loading: 'Đang tải…', simRequirement: 'Câu hỏi mô phỏng', none: 'Không có', assocFiles: 'Tệp liên quan', noAssoc: 'Không có tệp liên quan', playback: 'Xem lại simulation', step: 'Bước', playbackHint: 'Bắt đầu mô phỏng và Tương tác sâu là các bước trực tiếp nên không thể phát lại từ lịch sử.', unnamed: 'Simulation chưa đặt tên', rounds: 'vòng', unknownFile: 'Tệp không xác định'
  },
  es: {
    nav: 'Navegación principal', home: 'Inicio de SAMKY Studio', noUi: 'Sin interfaz', github: 'GitHub',
    eyebrow: 'Espacio de simulación de eventos', titleA: 'Prueba un futuro', titleB: 'antes de que ocurra.',
    intro: 'Convierte el material de un evento en una sociedad de agentes, observa reacciones en cadena y descubre los escenarios que merecen atención.',
    environment: 'ENTORNO ACTUAL', checking: 'Comprobando servicios…', ready: 'Listo para simular', setup: 'Configuración necesaria', refresh: 'Comprobar el sistema de nuevo',
    model: 'Modelo', neo4j: 'Neo4j', mode: 'Modo', online: 'Online', offline: 'Offline', connected: 'Conectado', disconnected: 'Sin conexión',
    bothDown: 'El servicio de modelos y Neo4j no responden. Completa la configuración antes de empezar.', neoDown: 'Neo4j no responde.', modelDown: 'El servicio de modelos no responde.',
    flowLabel: 'Flujo de simulación', flow1: 'Leer el contexto', flow1b: 'Documentos → grafo de conocimiento', flow2: 'Crear la sociedad', flow2b: 'Personas → interacciones multiagente', flow3: 'Extraer señales', flow3b: 'Cronología → informe de escenarios',
    newEvent: 'SIMULACIÓN / NUEVA', create: 'Crear una simulación de evento', privacy: 'Tus datos, bajo tu control',
    eventName: 'Nombre del evento', optional: 'Opcional', eventPlaceholder: 'Ejemplo: Reacciones a una nueva política',
    question: 'Pregunta de simulación', questionPlaceholder: '¿Qué podría ocurrir, quién reaccionará y qué señales debemos observar?',
    sources: 'Fuentes de contexto', drop: 'Suelta aquí PDF, Markdown o TXT', browse: 'o haz clic para elegir · máximo 50 MB', add: '+ Añadir documentos', remove: 'Eliminar',
    invalidFile: 'Algunos archivos se omitieron por formato no compatible o por superar 50 MB.', documents: 'documentos', nextSetup: 'Configura los agentes en el siguiente paso', launch: 'Iniciar simulación', opening: 'Abriendo el espacio…',
    headlessTitle: '¿Prefieres automatizar sin interfaz?', headlessBody: 'La CLI utiliza el mismo flujo y API de SAM.', copy: 'Copiar comando', copied: 'Copiado',
    records: 'Historial de simulaciones', graphConstruction: 'Construcción del grafo', envSetup: 'Configuración del entorno', analysisReport: 'Informe de análisis', filesMore: 'archivos más', noFiles: 'Sin archivos', loading: 'Cargando…', simRequirement: 'Pregunta de simulación', none: 'Ninguno', assocFiles: 'Archivos asociados', noAssoc: 'Sin archivos asociados', playback: 'Reproducción de la simulación', step: 'Paso', playbackHint: 'Iniciar simulación e Interacción profunda son pasos en vivo y no se pueden reproducir desde el historial.', unnamed: 'Simulación sin nombre', rounds: 'rondas', unknownFile: 'Archivo desconocido'
  }
}

export function useI18n() {
  const language = computed({ get: () => locale.value, set: value => { if (supported.includes(value)) locale.value = value } })
  const t = key => messages[locale.value]?.[key] || messages.en[key] || key
  return { locale: language, t, supported }
}

watch(locale, value => {
  localStorage.setItem('mirofish:locale', value)
  document.documentElement.lang = value
}, { immediate: true })
