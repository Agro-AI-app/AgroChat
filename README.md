# AgroChat

AgroChat is a six-profile AI workspace built on [Open WebUI 0.13.4](https://github.com/open-webui/open-webui/tree/v0.13.4). It keeps the native chat, model selector, projects, document retrieval, and tool interface. AgroChat adds a profile picker, account settings, managed Azure connections, and scheduled memory.

## Run locally

Use Python 3.12 and [uv](https://docs.astral.sh/uv/). Put the two Azure keys in the ignored `.env` file (see [`.env.example`](.env.example)). If `.env` already exists, keep it and add any missing settings.

```sh
uv venv --python 3.12 .venv
uv pip install --torch-backend cpu -r requirements.txt
.venv/bin/python -m agrochat
```

Open **http://127.0.0.1:8080**. Local state lives in `.data/` (SQLite, Chroma, uploads, and a generated session secret). If you run AgroChat with `docker compose up --build`, open **http://127.0.0.1** instead. Compose publishes port 80 on loopback, sets `AGROCHAT_ORIGIN` to match, and uses a named volume.

On the picker, use **Add profile**, or select an existing name and enter its password. Register with a first name, surname, password and confirmation. If the operator configures an enrollment code, new profiles also enter that code. Profile names and initials are visible on the opening screen. The **Account & memory** link in the chat sidebar opens optional photo settings, memories, sign-out, and account closure. Closure requires opening the review dialog, typing your full name, and re-entering your password.

### Models, projects, and memory

- The dropdown offers `gpt-6.2-sol` and `gpt-6.2-astra`. Chat uses Azure’s [Responses API](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses) at `https://agroai-dev.services.ai.azure.com/openai/v1/responses` so reasoning and native tools can be used together. Chat keys are held server-side in `AZURE_CHAT_API_KEY`.
- New chats start with **Web Search** enabled for both models, using DuckDuckGo by default. The model can search when it needs current information. Turn it off for a chat from the composer’s **+** menu, or set `ENABLE_WEB_SEARCH=false` to disable it for the whole app.
- RAG embeds uploads and queries with `text-embedding-3-large` (3,072 dimensions) using `AZURE_EMBEDDING_API_KEY`. The verified route is `https://agro-llm.services.ai.azure.com/openai/v1/embeddings`; the same host’s bare `/embeddings` path returns 404.
- Use **Projects** in the sidebar to create a private Open WebUI folder with its own chats, instructions, and documents. Ask about an uploaded file in its chat or attach the file to the project. Chats already in a project cannot be moved to another scope, archiving retains their project, and project deletion also deletes its chats. Subfolders are separate memory scopes.
- Every hour by default (`AGROCHAT_MEMORY_INTERVAL_SECONDS`), the worker summarizes saved chat branches and updates each project and profile from the most recent 20 eligible chats per scope. Chats whose last activity is older than seven days are excluded from the next refresh. Temporary chats are excluded. Summaries are cached when the source has not changed. The current chat receives its own summary and its project’s summary, if any, plus general profile memory. Standalone chats contribute the free-text general summary; project chats contribute only allowlisted reply preferences (detail, format, units, and tone).
- Users can review, pause, and clear summaries in **Account & memory**. Pausing stops scheduled updates and use of existing summaries. Clearing leaves the original chats intact; later chat activity can build fresh memory.

### Add an MCP server

Open WebUI's [native MCP integration](https://docs.openwebui.com/features/extensibility/mcp/) uses Streamable HTTP. Set `TOOL_SERVER_CONNECTIONS` to an operator-managed JSON array and restart. On Azure, provide it through the optional Key Vault secret in the deployment template. For example, this grants all six signed-in profiles access to a server:

```json
[
  {
    "type": "mcp",
    "url": "https://tools.example.org/mcp",
    "auth_type": "none",
    "info": { "id": "farm-tools", "name": "Farm tools" },
    "config": {
      "enable": true,
      "access_grants": [{ "principal_type": "user", "principal_id": "*", "permission": "read" }]
    }
  }
]
```

Choose the server in the chat composer’s **More → Tools** menu. For a bearer-authenticated server, use `"auth_type": "bearer"` and a `"key"` in the same connection object. No production MCP server is configured by default.

## Deploy on Azure

Use [Azure Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview) with a single always-running replica (1 vCPU / 2 GiB to start). Its ingress provides HTTPS, WebSockets, and the default `*.azurecontainerapps.io` hostname. One running worker keeps memory updates on schedule. PostgreSQL stores accounts and conversations; pgvector stores embeddings; a private Azure Blob container stores uploads. This keeps persistent state off the container filesystem.

Configure the existing Container App with a PostgreSQL `DATABASE_URL` before enabling the GitHub auto-deploy workflow. The workflow updates the image; the deployment template configures the database and storage. AgroChat refuses to start on Azure Container Apps without a PostgreSQL URL because a replica or revision change can discard profiles and chats stored in container-local SQLite.

1. Use an existing Container Apps environment, Azure Container Registry, PostgreSQL Flexible Server, Blob container, Key Vault, and user-assigned managed identity in the target Azure subscription. The app must be able to reach the database, registry, Key Vault, and Blob service from the Container Apps environment.
2. Enable the `vector` extension on the server and run `CREATE EXTENSION IF NOT EXISTS vector;` in a new AgroChat database. Use pgvector **0.7+** for `halfvec`. The app role needs permission to create its application tables. Store a TLS-enabled URL (for example `postgresql://USER:ENCODED_PASSWORD@HOST:5432/agrochat?sslmode=require`) as a Key Vault secret.
3. Give the managed identity **AcrPull**, **Key Vault Secrets User**, and **Storage Blob Data Contributor** on the corresponding resources. Store both model keys and a stable random `WEBUI_SECRET_KEY` in Key Vault, and use their secret URIs in the deployment parameters. You can also set `enrollmentCodeSecretUri` for an optional shared registration code.
4. Build the image with ACR and deploy [`deploy/container-app.bicep`](deploy/container-app.bicep). The container listens on port `80`, and the template uses that port for ingress and health probes. The template outputs the Azure-provided URL. The app derives its canonical origin from the stable Container Apps name and environment DNS suffix.

```sh
az acr build --registry "$ACR_NAME" --image "agrochat:$RELEASE" .
az deployment group create --resource-group "$RESOURCE_GROUP" \
  --template-file deploy/container-app.bicep \
  --parameters environmentId="$ENVIRONMENT_ID" location="$REGION" \
    image="$ACR_LOGIN_SERVER/agrochat:$RELEASE" registryServer="$ACR_LOGIN_SERVER" \
    identityId="$IDENTITY_ID" identityClientId="$IDENTITY_CLIENT_ID" \
    storageEndpoint="$STORAGE_ENDPOINT" databaseSecretUri="$DATABASE_SECRET_URI" \
    chatKeySecretUri="$CHAT_KEY_SECRET_URI" embeddingKeySecretUri="$EMBEDDINGS_KEY_SECRET_URI" \
    sessionKeySecretUri="$SESSION_KEY_SECRET_URI" \
  --query properties.outputs.url.value -o tsv
```

## Headless verification

The smoke test uses Chromium through Playwright; it does not need a desktop browser. Start it with real model keys in `.env`; it creates an isolated local database and sends only synthetic test content to Azure. It covers registration, sign-in, chat, profile photo, the six-seat cap, credential entry restrictions, deletion, RAG, MCP tool execution, and memory scope/expiry.

```sh
uv pip install playwright
.venv/bin/python -m playwright install --with-deps chromium
.venv/bin/python tests/run_smoke.py
```
