// =============================================================================
// Octopus Deploy → Microsoft Sentinel  |  main.bicep
// =============================================================================
// Provisions:
//   • Log Analytics Workspace + Microsoft Sentinel solution
//   • Custom table  OctopusAuditEvents_CL
//   • Data Collection Endpoint (DCE)
//   • Data Collection Rule   (DCR)  linked to the custom table
//   • Azure Storage Account  (checkpoint table)
//   • Azure Key Vault         (secrets)
//   • Consumption Function App + App Service Plan
//   • System-assigned Managed Identity on Function App
//   • RBAC: Monitoring Metrics Publisher → Function App MI
//   • RBAC: Storage Table Data Contributor → Function App MI
//   • RBAC: Key Vault Secrets User → Function App MI
// =============================================================================

targetScope = 'resourceGroup'

// --------------- Parameters --------------------------------------------------

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Prefix used to name all resources. 3-12 alphanumeric chars.')
@minLength(3)
@maxLength(12)
param prefix string = 'octosentinel'

@description('Octopus Deploy server URL (e.g. https://myorg.octopus.app).')
param octopusServerUrl string

@description('Name of the Key Vault secret that stores the Octopus API key.')
param octopusApiKeySecretName string = 'OctopusApiKey'

@description('Log retention in days.')
@minValue(30)
@maxValue(730)
param logRetentionDays int = 90

@description('Tags applied to every resource.')
param tags object = {
  solution:    'OctopusSentinel'
  environment: 'production'
}

// --------------- Variables ---------------------------------------------------

var uniqueSuffix     = uniqueString(resourceGroup().id, prefix)
var workspaceName    = '${prefix}-law-${uniqueSuffix}'
var dceName          = '${prefix}-dce-${uniqueSuffix}'
var dcrName          = '${prefix}-dcr-${uniqueSuffix}'
var storageAccName   = '${prefix}st${uniqueSuffix}'   // max 24 chars, no hyphens
var kvName           = '${prefix}-kv-${uniqueSuffix}'
var appPlanName      = '${prefix}-asp-${uniqueSuffix}'
var functionAppName  = '${prefix}-func-${uniqueSuffix}'
var appInsightsName  = '${prefix}-ai-${uniqueSuffix}'
var streamName       = 'Custom-OctopusAuditEvents_CL'
var tableName        = 'OctopusAuditEvents_CL'

// --------------- Log Analytics Workspace -------------------------------------

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name:     workspaceName
  location: location
  tags:     tags
  properties: {
    sku:                     { name: 'PerGB2018' }
    retentionInDays:         logRetentionDays
    publicNetworkAccessForQuery:    'Enabled'
    publicNetworkAccessForIngestion: 'Enabled'
  }
}

// --------------- Microsoft Sentinel ------------------------------------------

resource sentinel 'Microsoft.OperationsManagement/solutions@2015-11-01-preview' = {
  name:     'SecurityInsights(${workspaceName})'
  location: location
  tags:     tags
  plan: {
    name:          'SecurityInsights(${workspaceName})'
    publisher:     'Microsoft'
    product:       'OMSGallery/SecurityInsights'
    promotionCode: ''
  }
  properties: {
    workspaceResourceId: workspace.id
  }
}

// --------------- Custom Table Schema -----------------------------------------

resource customTable 'Microsoft.OperationalInsights/workspaces/tables@2023-09-01' = {
  parent: workspace
  name:   tableName
  properties: {
    retentionInDays: logRetentionDays
    schema: {
      name: tableName
      columns: [
        { name: 'TimeGenerated',   type: 'datetime'  }
        { name: 'IngestionTime',   type: 'datetime'  }
        { name: 'EventId',         type: 'string'    }
        { name: 'AutoId',          type: 'int'       }
        { name: 'EventCategory',   type: 'string'    }
        { name: 'EventType',       type: 'string'    }
        { name: 'UserId',          type: 'string'    }
        { name: 'Username',        type: 'string'    }
        { name: 'UserDisplayName', type: 'string'    }
        { name: 'IsService',       type: 'boolean'   }
        { name: 'IpAddress',       type: 'string'    }
        { name: 'UserAgent',       type: 'string'    }
        { name: 'SpaceId',         type: 'string'    }
        { name: 'ProjectId',       type: 'string'    }
        { name: 'ProjectName',     type: 'string'    }
        { name: 'EnvironmentId',   type: 'string'    }
        { name: 'EnvironmentName', type: 'string'    }
        { name: 'ReleaseId',       type: 'string'    }
        { name: 'ReleaseVersion',  type: 'string'    }
        { name: 'DeploymentId',    type: 'string'    }
        { name: 'TenantId',        type: 'string'    }
        { name: 'TenantName',      type: 'string'    }
        { name: 'ChannelId',       type: 'string'    }
        { name: 'MachineName',     type: 'string'    }
        { name: 'Outcome',         type: 'string'    }
        { name: 'Message',         type: 'string'    }
        { name: 'ChangeDetails',   type: 'string'    }
        { name: 'MitreTactic',     type: 'string'    }
        { name: 'MitreTechnique',  type: 'string'    }
      ]
    }
  }
  dependsOn: [ sentinel ]
}

// --------------- Data Collection Endpoint ------------------------------------

resource dce 'Microsoft.Insights/dataCollectionEndpoints@2023-03-11' = {
  name:     dceName
  location: location
  tags:     tags
  properties: {
    networkAcls: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

// --------------- Data Collection Rule ----------------------------------------

resource dcr 'Microsoft.Insights/dataCollectionRules@2023-03-11' = {
  name:     dcrName
  location: location
  tags:     tags
  properties: {
    dataCollectionEndpointId: dce.id
    streamDeclarations: {
      '${streamName}': {
        columns: [
          { name: 'TimeGenerated',   type: 'datetime'  }
          { name: 'IngestionTime',   type: 'datetime'  }
          { name: 'EventId',         type: 'string'    }
          { name: 'AutoId',          type: 'int'       }
          { name: 'EventCategory',   type: 'string'    }
          { name: 'EventType',       type: 'string'    }
          { name: 'UserId',          type: 'string'    }
          { name: 'Username',        type: 'string'    }
          { name: 'UserDisplayName', type: 'string'    }
          { name: 'IsService',       type: 'boolean'   }
          { name: 'IpAddress',       type: 'string'    }
          { name: 'UserAgent',       type: 'string'    }
          { name: 'SpaceId',         type: 'string'    }
          { name: 'ProjectId',       type: 'string'    }
          { name: 'ProjectName',     type: 'string'    }
          { name: 'EnvironmentId',   type: 'string'    }
          { name: 'EnvironmentName', type: 'string'    }
          { name: 'ReleaseId',       type: 'string'    }
          { name: 'ReleaseVersion',  type: 'string'    }
          { name: 'DeploymentId',    type: 'string'    }
          { name: 'TenantId',        type: 'string'    }
          { name: 'TenantName',      type: 'string'    }
          { name: 'ChannelId',       type: 'string'    }
          { name: 'MachineName',     type: 'string'    }
          { name: 'Outcome',         type: 'string'    }
          { name: 'Message',         type: 'string'    }
          { name: 'ChangeDetails',   type: 'string'    }
          { name: 'MitreTactic',     type: 'string'    }
          { name: 'MitreTechnique',  type: 'string'    }
        ]
      }
    }
    destinations: {
      logAnalytics: [
        {
          name:                'OctopusWorkspace'
          workspaceResourceId: workspace.id
        }
      ]
    }
    dataFlows: [
      {
        streams:      [ streamName ]
        destinations: [ 'OctopusWorkspace' ]
        transformKql: 'source'
        outputStream: streamName
      }
    ]
  }
  dependsOn: [ customTable ]
}

// --------------- Storage Account (checkpoint) --------------------------------

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name:     storageAccName
  location: location
  tags:     tags
  sku:      { name: 'Standard_LRS' }
  kind:     'StorageV2'
  properties: {
    minimumTlsVersion:       'TLS1_2'
    allowBlobPublicAccess:   false
    supportsHttpsTrafficOnly: true
    accessTier:              'Hot'
  }
}

// --------------- Key Vault ---------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name:     kvName
  location: location
  tags:     tags
  properties: {
    sku:                   { family: 'A', name: 'standard' }
    tenantId:              subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete:      true
    softDeleteRetentionInDays: 90
    networkAcls: {
      defaultAction: 'Allow'
      bypass:        'AzureServices'
    }
  }
}

// --------------- Application Insights ----------------------------------------

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name:     appInsightsName
  location: location
  tags:     tags
  kind:     'web'
  properties: {
    Application_Type:                'web'
    WorkspaceResourceId:             workspace.id
    IngestionMode:                   'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery:     'Enabled'
  }
}

// --------------- App Service Plan (Consumption) ------------------------------

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name:     appPlanName
  location: location
  tags:     tags
  sku:      { name: 'Y1', tier: 'Dynamic' }
  kind:     'functionapp'
  properties: {
    reserved: true   // Linux
  }
}

// --------------- Function App ------------------------------------------------

resource functionApp 'Microsoft.Web/sites@2023-12-01' = {
  name:     functionAppName
  location: location
  tags:     tags
  kind:     'functionapp,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly:    true
    siteConfig: {
      pythonVersion:          '3.11'
      linuxFxVersion:         'Python|3.11'
      functionAppScaleLimit:  1   // Serial execution; prevents duplicate ingestion
      minTlsVersion:          '1.2'
      ftpsState:              'Disabled'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName';           value: storageAccount.name }
        { name: 'FUNCTIONS_EXTENSION_VERSION';                value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME';                   value: 'python' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING';      value: appInsights.properties.ConnectionString }
        { name: 'OCTOPUS_SERVER_URL';                         value: octopusServerUrl }
        { name: 'OCTOPUS_API_KEY';                            value: '@Microsoft.KeyVault(VaultName=${kvName};SecretName=${octopusApiKeySecretName})' }
        { name: 'SENTINEL_DCE_ENDPOINT';                      value: dce.properties.logsIngestion.endpoint }
        { name: 'SENTINEL_DCR_IMMUTABLE_ID';                  value: dcr.properties.immutableId }
        { name: 'SENTINEL_STREAM_NAME';                       value: streamName }
        { name: 'CHECKPOINT_STORAGE_ACCOUNT_URL';             value: 'https://${storageAccount.name}.table.core.windows.net' }
      ]
    }
  }
}

// --------------- RBAC Assignments --------------------------------------------

// Monitoring Metrics Publisher → send logs to DCR
resource roleMonitoringPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(dcr.id, functionApp.id, 'MonitoringMetricsPublisher')
  scope: dcr
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '3913510d-42f4-4e42-8a64-420c390055eb'   // Monitoring Metrics Publisher
    )
    principalId:   functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Table Data Contributor → read/write checkpoint table
resource roleStorageTable 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(storageAccount.id, functionApp.id, 'StorageTableDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'   // Storage Table Data Contributor
    )
    principalId:   functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User → read API key secret
resource roleKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(keyVault.id, functionApp.id, 'KeyVaultSecretsUser')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'   // Key Vault Secrets User
    )
    principalId:   functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Storage Blob Data Contributor → AzureWebJobsStorage for Function runtime
resource roleStorageBlob 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name:  guid(storageAccount.id, functionApp.id, 'StorageBlobDataContributor')
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'ba92f5b4-2d11-453d-a403-e96b0029c9fe'   // Storage Blob Data Contributor
    )
    principalId:   functionApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// --------------- Outputs -----------------------------------------------------

output workspaceId         string = workspace.id
output workspaceName       string = workspace.name
output dceEndpoint         string = dce.properties.logsIngestion.endpoint
output dcrImmutableId      string = dcr.properties.immutableId
output streamName          string = streamName
output functionAppName     string = functionApp.name
output functionAppPrincipalId string = functionApp.identity.principalId
output keyVaultName        string = keyVault.name
output storageAccountName  string = storageAccount.name
