@description('Existing Container Apps environment resource ID.')
param environmentId string
param location string = resourceGroup().location
param appName string = 'agrochat'
@description('Fully qualified image reference from Azure Container Registry; use an immutable tag or digest.')
param image string
param registryServer string
param identityId string
param identityClientId string
param storageEndpoint string
param storageContainer string = 'agrochat'

@description('Key Vault secret URI for the PostgreSQL SQLAlchemy URL including TLS options.')
param databaseSecretUri string
param chatKeySecretUri string
param embeddingKeySecretUri string
param imageKeySecretUri string = ''
param sessionKeySecretUri string
param enrollmentCodeSecretUri string = ''
@description('Optional Key Vault secret URI for the Open WebUI TOOL_SERVER_CONNECTIONS JSON array.')
param toolsSecretUri string = ''

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 80
        transport: 'auto'
        allowInsecure: false
      }
      registries: [{
        server: registryServer
        identity: identityId
      }]
      secrets: concat([
        { name: 'database', keyVaultUrl: databaseSecretUri, identity: identityId }
        { name: 'chat-key', keyVaultUrl: chatKeySecretUri, identity: identityId }
        { name: 'embedding-key', keyVaultUrl: embeddingKeySecretUri, identity: identityId }
        { name: 'session-key', keyVaultUrl: sessionKeySecretUri, identity: identityId }
      ], empty(enrollmentCodeSecretUri) ? [] : [{ name: 'enrollment-code', keyVaultUrl: enrollmentCodeSecretUri, identity: identityId }],
      empty(imageKeySecretUri) ? [] : [{ name: 'image-key', keyVaultUrl: imageKeySecretUri, identity: identityId }],
      empty(toolsSecretUri) ? [] : [{ name: 'tools', keyVaultUrl: toolsSecretUri, identity: identityId }])
    }
    template: {
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
      containers: [{
        name: 'agrochat'
        image: image
        resources: {
          cpu: json('1')
          memory: '2Gi'
        }
        env: concat([
          { name: 'DATABASE_URL', secretRef: 'database' }
          { name: 'AZURE_CHAT_API_KEY', secretRef: 'chat-key' }
          { name: 'AZURE_EMBEDDING_API_KEY', secretRef: 'embedding-key' }
          { name: 'WEBUI_SECRET_KEY', secretRef: 'session-key' }
          { name: 'AZURE_CLIENT_ID', value: identityClientId }
          { name: 'STORAGE_PROVIDER', value: 'azure' }
          { name: 'AZURE_STORAGE_ENDPOINT', value: storageEndpoint }
          { name: 'AZURE_STORAGE_CONTAINER_NAME', value: storageContainer }
          { name: 'VECTOR_DB', value: 'pgvector' }
          { name: 'PGVECTOR_USE_HALFVEC', value: 'true' }
          { name: 'PGVECTOR_INITIALIZE_MAX_VECTOR_LENGTH', value: '3072' }
          { name: 'PGVECTOR_CREATE_EXTENSION', value: 'false' }
        ], empty(enrollmentCodeSecretUri) ? [] : [{ name: 'AGROCHAT_ENROLLMENT_CODE', secretRef: 'enrollment-code' }],
        empty(imageKeySecretUri) ? [] : [{ name: 'AZURE_IMAGE_API_KEY', secretRef: 'image-key' }],
        empty(toolsSecretUri) ? [] : [{ name: 'TOOL_SERVER_CONNECTIONS', secretRef: 'tools' }])
        probes: [
          {
            type: 'Startup'
            httpGet: { path: '/ready', port: 80 }
            periodSeconds: 5
            failureThreshold: 36
          }
          {
            type: 'Readiness'
            httpGet: { path: '/ready', port: 80 }
            periodSeconds: 10
          }
          {
            type: 'Liveness'
            httpGet: { path: '/health', port: 80 }
            periodSeconds: 20
          }
        ]
      }]
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
