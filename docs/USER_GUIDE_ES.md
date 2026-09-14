# Guía de SAMKY Studio

SAMKY Studio ofrece una interfaz centrada en eventos basada en MiroFish-Offline: procesa documentos, construye un grafo de conocimiento, crea una sociedad de agentes, ejecuta interacciones y genera informes.

Idiomas: [English](USER_GUIDE.md) · [Tiếng Việt](USER_GUIDE_VI.md)

## Elegir el modo

| Modo | Modelo | Datos del evento |
|---|---|---|
| Offline | Ollama en tu equipo | Permanecen en tu equipo |
| Online | Endpoint compatible con OpenAI | Los prompts se envían al proveedor configurado |
| Sin interfaz | La misma configuración del servidor | Igual que el modo seleccionado |

Neo4j guarda el grafo localmente. En la configuración online predeterminada, los embeddings también se calculan con Ollama local.

## Ejecutar offline con Docker

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker exec mirofish-ollama ollama pull qwen2.5:7b
docker exec mirofish-ollama ollama pull nomic-embed-text
```

Abre `http://localhost:3000` y confirma que **Entorno actual** muestra el modelo y Neo4j como disponibles.

## Usar un modelo online

```powershell
Copy-Item .env.online.example .env.online
```

Edita `.env.online` y define `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` y `OPENAI_API_KEY`.

```powershell
docker compose -f compose.online.yml --env-file .env.online up -d --build
docker exec mirofish-embeddings ollama pull nomic-embed-text
```

Puedes introducir o eliminar una clave API en la configuración. Se conserva en la memoria del servidor y no en el almacenamiento del navegador.

## Crear una simulación

1. Escribe un nombre opcional.
2. Formula una pregunta con horizonte temporal, actores y señales que deseas observar.
3. Añade al menos un PDF, Markdown o TXT.
4. Elige online/offline, endpoint, modelo y clave opcional. Selecciona las rondas desde el principio; **se recomiendan 60**.
5. Pulsa **Iniciar simulación**. La preparación es automática; aparecen el grafo y la barra de progreso.
6. Genera un informe o entrevista a los agentes individualmente o en grupo. Consulta [la guía de interfaz](STUDIO_UI.md).

## Ejecutar sin interfaz

El servidor debe estar iniciado.

```powershell
python backend/scripts/sam_cli.py doctor
python backend/scripts/sam_cli.py run `
  --file .\examples\event.md `
  --goal "¿Cómo reaccionarán los actores durante los próximos 30 días?" `
  --rounds 10 `
  --wait `
  --report
```

Repite `--file` para usar varias fuentes. El resultado JSON incluye los identificadores del proyecto, grafo, simulación e informe.

## Problemas frecuentes

- **Modelo no disponible:** comprueba `ollama list` y que el nombre coincida con `.env`.
- **Neo4j no responde:** revisa `docker compose ps` y la contraseña.
- **Error online 401/403:** revisa la clave, la URL `/v1` y el acceso al modelo.
- **Falta memoria:** usa un modelo menor, menos rondas/agentes o un endpoint online.

No envíes secretos ni datos sensibles a un proveedor online. Conserva la configuración de cada ejecución y valida las conclusiones importantes con expertos del dominio.
