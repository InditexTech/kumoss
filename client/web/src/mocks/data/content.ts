// SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
//
// SPDX-License-Identifier: Apache-2.0

/**
 * The mock content library: Terraform code, plans, reports and
 * conversation turns for every scenario the UI can land on.
 *
 * This file holds *content only*. The backend never ships it as one
 * blob — each file, the plan and the report are separate artifacts
 * behind their own presigned URL (see `artifacts.ts`), assembled into
 * rounds by `sessions.ts`. The bundles below stay in the LLM's
 * `<filename.tf>` / `<Terraform_Plan>` tagged form because that is how
 * they were captured; `splitBundle` takes them apart again.
 */

import type { RawHistoryTurn, ReportType } from "@/types/api";
import type { TerraformReport } from "@/types/index";

// ─── Mock Content Types ───────────────────────────────────────

export type MockContentType =
  | "generate"
  | "generate_partial"
  | "generate_multi"
  | "drift"
  | "drift_failed"
  | "drift_partial"
  | "partial_drift"
  | "partial_drift_failed"
  | "partial_drift_partial"
  | "apply"
  | "apply_create"
  | "apply_create_update"
  | "apply_destroy"
  | "apply_mixed"
  | "import"
  | "import_failed"
  | "import_partial"
  | "destructive"
  | "remove_resource";

// ─── Terraform Code (XML-tagged response) ─────────────────────
// The LLM wraps each file in <filename.tf> tags and the plan in
// <Terraform_Plan> tags. The frontend splits these via regex in
// processTerraformPlan() and processFiles().

const RESPONSE_GENERATE = `<main.tf>
resource "azurerm_resource_group" "rg" {
  name     = "rg-contoso-dev"
  location = var.location

  tags = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosodev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  tags = {
    environment = var.environment
  }
}
</main.tf>
<variables.tf>
variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}
</variables.tf>
<outputs.tf>
output "storage_account_id" {
  description = "ID of the created storage account"
  value       = azurerm_storage_account.sa.id
}

output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.rg.name
}
</outputs.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  + create
  ~ update in-place

Terraform will perform the following actions:

  # azurerm_resource_group.rg will be created
  + resource "azurerm_resource_group" "rg" {
      + id       = (known after apply)
      + location = "westeurope"
      + name     = "rg-contoso-dev"
      + tags     = {
          + "environment" = "dev"
          + "managed_by"  = "terraform"
        }
    }

  # azurerm_storage_account.sa will be created
  + resource "azurerm_storage_account" "sa" {
      + access_tier               = (known after apply)
      + id                        = (known after apply)
      + location                  = "westeurope"
      + min_tls_version           = "TLS1_2"
      + name                      = "stcontosodev001"
      + resource_group_name       = "rg-contoso-dev"
      + account_replication_type  = "LRS"
      + account_tier              = "Standard"
      + tags                      = {
          + "environment" = "dev"
        }
    }

  # azurerm_virtual_network.vnet will be updated in-place
  ~ resource "azurerm_virtual_network" "vnet" {
        id                = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/virtualNetworks/vnet-contoso-dev"
        name              = "vnet-contoso-dev"
      ~ address_space     = [
            "10.0.0.0/16",
          + "10.1.0.0/24",
        ]
    }

Plan: 2 to add, 1 to change, 0 to destroy.
</Terraform_Plan>`;

const RESPONSE_DESTRUCTIVE = `<main.tf>
resource "azurerm_container_group" "backend" {
  name                = "ci-contoso-backend-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  ip_address_type     = "Private"
  subnet_ids          = [azurerm_subnet.containers.id]

  container {
    name   = "api"
    image  = "contosoacr.azurecr.io/backend:latest"
    cpu    = 2
    memory = 4

    ports {
      port     = 8000
      protocol = "TCP"
    }

    environment_variables = {
      DATABASE_URL = "postgresql://\${azurerm_postgresql_flexible_server.db.fqdn}:5432/contoso"
    }
  }
}

resource "azurerm_container_registry" "acr" {
  name                = "contosoacr"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Standard"
  admin_enabled       = false
}

resource "azurerm_subnet" "containers" {
  name                 = "snet-containers"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.3.0/24"]

  delegation {
    name = "container-delegation"
    service_delegation {
      name = "Microsoft.ContainerInstance/containerGroups"
    }
  }
}
</main.tf>
<variables.tf>
variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "container_image" {
  description = "Backend container image"
  type        = string
  default     = "contosoacr.azurecr.io/backend:latest"
}
</variables.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  + create
  - destroy
  -/+ destroy and then create replacement

Terraform will perform the following actions:

  # azurerm_container_group.backend will be created
  + resource "azurerm_container_group" "backend" {
      + id                  = (known after apply)
      + ip_address          = (known after apply)
      + name                = "ci-contoso-backend-dev"
      + location            = "westeurope"
      + resource_group_name = "rg-contoso-dev"
      + os_type             = "Linux"
    }

  # azurerm_container_registry.acr will be created
  + resource "azurerm_container_registry" "acr" {
      + id                  = (known after apply)
      + login_server        = (known after apply)
      + name                = "contosoacr"
      + sku                 = "Standard"
      + admin_enabled       = false
    }

  # azurerm_subnet.containers will be created
  + resource "azurerm_subnet" "containers" {
      + id                   = (known after apply)
      + name                 = "snet-containers"
      + address_prefixes     = ["10.0.3.0/24"]
    }

  # azurerm_virtual_machine.backend will be destroyed
  - resource "azurerm_virtual_machine" "backend" {
      - id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Compute/virtualMachines/vm-backend-dev" -> null
      - name                = "vm-backend-dev" -> null
      - location            = "westeurope" -> null
      - vm_size             = "Standard_D2s_v3" -> null
      - os_disk {
          - caching              = "ReadWrite" -> null
          - storage_account_type = "Premium_LRS" -> null
        }
    }

  # azurerm_lb.backend will be destroyed
  - resource "azurerm_lb" "backend" {
      - id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/loadBalancers/lb-backend-dev" -> null
      - name                = "lb-backend-dev" -> null
      - sku                 = "Standard" -> null
    }

  # azurerm_network_security_group.backend must be replaced
  -/+ resource "azurerm_network_security_group" "backend" {
      ~ id                  = "/subscriptions/a1b2c3d4/.../nsg-backend-dev" -> (known after apply)
        name                = "nsg-backend-dev"
      ~ security_rule       = [
          - {
              - name                       = "AllowSSH"
              - priority                   = 100
              - direction                  = "Inbound"
              - access                     = "Allow"
              - protocol                   = "Tcp"
              - destination_port_range     = "22"
            },
          + {
              + name                       = "AllowContainerPort"
              + priority                   = 100
              + direction                  = "Inbound"
              + access                     = "Allow"
              + protocol                   = "Tcp"
              + destination_port_range     = "8000"
            },
        ]
    }

Plan: 4 to add, 0 to change, 3 to destroy.
</Terraform_Plan>`;

// A *pure removal*: nothing is created or replaced, the resource blocks
// are simply gone from the configuration and the plan is destroy-only.
// This is the scenario an operator is asked to unblock before applying.
const RESPONSE_REMOVE_RESOURCE = `<analytics.tf>
resource "azurerm_resource_group" "analytics" {
  name     = "rg-contoso-analytics-pro"
  location = var.location

  tags = {
    environment = "pro"
    managed_by  = "terraform"
  }
}

resource "azurerm_storage_account" "lake" {
  name                     = "stcontosolakepro"
  resource_group_name      = azurerm_resource_group.analytics.name
  location                 = azurerm_resource_group.analytics.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  is_hns_enabled           = true

  min_tls_version = "TLS1_2"
}

# Removed: azurerm_data_factory.legacy_etl, azurerm_storage_account.etl_exports
# and azurerm_key_vault_secret.etl_connection. The nightly ETL pipeline was
# migrated to the streaming ingestion job on 2026-08-14 and is no longer used.
</analytics.tf>
<outputs.tf>
output "lake_storage_account_name" {
  description = "Primary data lake storage account"
  value       = azurerm_storage_account.lake.name
}

# Removed: the "etl_exports_endpoint" and "legacy_etl_factory_id" outputs,
# which referenced the decommissioned resources.
</outputs.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  - destroy

Terraform will perform the following actions:

  # azurerm_data_factory.legacy_etl will be destroyed
  - resource "azurerm_data_factory" "legacy_etl" {
      - id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-analytics-pro/providers/Microsoft.DataFactory/factories/adf-legacy-etl-pro" -> null
      - name                = "adf-legacy-etl-pro" -> null
      - location            = "westeurope" -> null
      - resource_group_name = "rg-contoso-analytics-pro" -> null
      - public_network_enabled = true -> null
    }

  # azurerm_storage_account.etl_exports will be destroyed
  - resource "azurerm_storage_account" "etl_exports" {
      - id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-analytics-pro/providers/Microsoft.Storage/storageAccounts/stetlexportspro" -> null
      - name                     = "stetlexportspro" -> null
      - account_tier             = "Standard" -> null
      - account_replication_type = "GRS" -> null
      - location                 = "westeurope" -> null
    }

  # azurerm_key_vault_secret.etl_connection will be destroyed
  - resource "azurerm_key_vault_secret" "etl_connection" {
      - id           = "https://kv-contoso-pro.vault.azure.net/secrets/etl-connection/9f2c" -> null
      - name         = "etl-connection" -> null
      - key_vault_id = "/subscriptions/a1b2c3d4/.../vaults/kv-contoso-pro" -> null
    }

Plan: 0 to add, 0 to change, 3 to destroy.

Changes to Outputs:
  - etl_exports_endpoint  = "https://stetlexportspro.blob.core.windows.net/" -> null
  - legacy_etl_factory_id = "/subscriptions/a1b2c3d4/.../factories/adf-legacy-etl-pro" -> null
</Terraform_Plan>`;

const RESPONSE_DRIFT = `<network.tf>
resource "azurerm_network_security_group" "nsg" {
  name                = "nsg-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/8"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "DenyAll"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.0.0.0/16"]

  subnet {
    name             = "snet-app"
    address_prefixes = ["10.0.1.0/24"]
  }
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosodev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}
</network.tf>
<variables.tf>
variable "allowed_cidr" {
  description = "Allowed CIDR block for inbound HTTPS"
  type        = string
  default     = "10.0.0.0/8"
}
</variables.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  ~ update in-place

Terraform will perform the following actions:

  # azurerm_storage_account.sa will be updated in-place
  ~ resource "azurerm_storage_account" "sa" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/stcontosodev001"
        name                     = "stcontosodev001"
      ~ account_tier             = "Premium" -> "Standard"
        # (8 unchanged attributes hidden)
    }

  # azurerm_virtual_network.vnet will be updated in-place
  ~ resource "azurerm_virtual_network" "vnet" {
        id                = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/virtualNetworks/vnet-contoso-dev"
        name              = "vnet-contoso-dev"
      ~ address_space     = [
            "10.0.0.0/16",
          - "10.1.0.0/16",
        ]
        # (3 unchanged attributes hidden)
    }

  # azurerm_network_security_group.nsg will be updated in-place
  ~ resource "azurerm_network_security_group" "nsg" {
        id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/networkSecurityGroups/nsg-contoso-dev"
        name                = "nsg-contoso-dev"
      ~ security_rule       = [
          ~ {
                name                       = "AllowHTTPS"
              ~ source_address_prefix      = "*" -> "10.0.0.0/8"
            },
          + {
              + name                       = "DenyAll"
              + priority                   = 4096
              + direction                  = "Inbound"
              + access                     = "Deny"
              + protocol                   = "*"
            },
        ]
    }

Plan: 0 to add, 3 to change, 0 to destroy.
</Terraform_Plan>`;

const RESPONSE_IMPORT = `<imports.tf>
import {
  to = azurerm_resource_group.legacy
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod"
}

import {
  to = azurerm_storage_account.legacy_sa
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.Storage/storageAccounts/stlegacyprod"
}

import {
  to = azurerm_key_vault.legacy_kv
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.KeyVault/vaults/kv-legacy-prod"
}

import {
  to = azurerm_postgresql_flexible_server.legacy_db
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-legacy-prod"
}
</imports.tf>
<resources.tf>
resource "azurerm_resource_group" "legacy" {
  name     = "rg-legacy-prod"
  location = "northeurope"

  tags = {
    managed_by  = "terraform"
    imported_at = "2026-06-11"
  }
}

resource "azurerm_storage_account" "legacy_sa" {
  name                     = "stlegacyprod"
  resource_group_name      = azurerm_resource_group.legacy.name
  location                 = azurerm_resource_group.legacy.location
  account_tier             = "Standard"
  account_replication_type = "GRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_key_vault" "legacy_kv" {
  name                     = "kv-legacy-prod"
  location                 = azurerm_resource_group.legacy.location
  resource_group_name      = azurerm_resource_group.legacy.name
  tenant_id                = data.azurerm_client_config.current.tenant_id
  sku_name                 = "standard"
  purge_protection_enabled = true
}

resource "azurerm_postgresql_flexible_server" "legacy_db" {
  name                   = "psql-legacy-prod"
  resource_group_name    = azurerm_resource_group.legacy.name
  location               = azurerm_resource_group.legacy.location
  administrator_login    = "contoso_admin"
  version                = "16"
  sku_name               = "GP_Standard_D2s_v3"
  storage_mb             = 65536
  backup_retention_days  = 30
  geo_redundant_backup_enabled = true
}
</resources.tf>
<variables.tf>
variable "tenant_id" {
  description = "Azure AD tenant ID"
  type        = string
}
</variables.tf>
<Terraform_Plan>
Terraform will perform the following actions:

  # azurerm_resource_group.legacy will be imported
    resource "azurerm_resource_group" "legacy" {
        id       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod"
        location = "northeurope"
        name     = "rg-legacy-prod"
        tags     = {}
    }

  # azurerm_storage_account.legacy_sa will be imported
    resource "azurerm_storage_account" "legacy_sa" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod/providers/Microsoft.Storage/storageAccounts/stlegacyprod"
        name                     = "stlegacyprod"
        account_tier             = "Standard"
        account_replication_type = "GRS"
        min_tls_version          = "TLS1_2"
    }

  # azurerm_key_vault.legacy_kv will be imported
    resource "azurerm_key_vault" "legacy_kv" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod/providers/Microsoft.KeyVault/vaults/kv-legacy-prod"
        name                     = "kv-legacy-prod"
        sku_name                 = "standard"
        purge_protection_enabled = true
    }

  # azurerm_postgresql_flexible_server.legacy_db will be imported
    resource "azurerm_postgresql_flexible_server" "legacy_db" {
        id                    = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-legacy-prod"
        name                  = "psql-legacy-prod"
        version               = "16"
        sku_name              = "GP_Standard_D2s_v3"
        storage_mb            = 65536
    }

Plan: 4 to import, 0 to add, 0 to change, 0 to destroy.
</Terraform_Plan>`;

const RESPONSE_APPLY = `<main.tf>
resource "azurerm_postgresql_flexible_server" "db" {
  name                   = "contoso-psql-weu1-dev-001"
  resource_group_name    = azurerm_resource_group.rg.name
  location               = azurerm_resource_group.rg.location
  administrator_login    = "contoso_admin"
  version                = "16"
  sku_name               = "GP_Standard_D2s_v3"
  storage_mb             = 65536
  backup_retention_days  = 14
  zone                   = "1"

  tags = {
    environment = var.environment
    project     = "contoso"
    managed_by  = "terraform"
  }
}

resource "azurerm_postgresql_flexible_server_database" "app" {
  name      = "contoso_dev"
  server_id = azurerm_postgresql_flexible_server.db.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_storage_account" "sa" {
  name                       = "contososaweu1dev001"
  resource_group_name        = azurerm_resource_group.rg.name
  location                   = azurerm_resource_group.rg.location
  account_tier               = "Standard"
  account_replication_type   = "ZRS"
  min_tls_version            = "TLS1_2"
  https_traffic_only_enabled = true

  blob_properties {
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }

  tags = {
    environment = var.environment
    project     = "contoso"
    managed_by  = "terraform"
  }
}

resource "azurerm_key_vault_secret" "db_connection_string" {
  name         = "contoso-db-connection-string-dev"
  value        = "postgresql://\${azurerm_postgresql_flexible_server.db.administrator_login}@\${azurerm_postgresql_flexible_server.db.fqdn}:5432/\${azurerm_postgresql_flexible_server_database.app.name}?sslmode=require"
  key_vault_id = azurerm_key_vault.kv.id
}

resource "azurerm_management_lock" "db_lock" {
  name       = "contoso-psql-weu1-dev-001-lock"
  scope      = azurerm_postgresql_flexible_server.db.id
  lock_level = "CanNotDelete"
  notes      = "Critical database — prevent accidental deletion"
}
</main.tf>
<variables.tf>
variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "westeurope"
}
</variables.tf>
<Terraform_Plan>
azurerm_postgresql_flexible_server.db: Creating...
azurerm_postgresql_flexible_server.db: Still creating... [30s elapsed]
azurerm_postgresql_flexible_server.db: Still creating... [1m0s elapsed]
azurerm_postgresql_flexible_server.db: Still creating... [1m30s elapsed]
azurerm_postgresql_flexible_server.db: Creation complete after 1m52s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.DBforPostgreSQL/flexibleServers/contoso-psql-weu1-dev-001]
azurerm_postgresql_flexible_server_database.app: Creating...
azurerm_postgresql_flexible_server_database.app: Creation complete after 3s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.DBforPostgreSQL/flexibleServers/contoso-psql-weu1-dev-001/databases/contoso_dev]
azurerm_storage_account.sa: Creating...
azurerm_storage_account.sa: Still creating... [10s elapsed]
azurerm_storage_account.sa: Creation complete after 28s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/contososaweu1dev001]
azurerm_key_vault_secret.db_connection_string: Creating...
azurerm_key_vault_secret.db_connection_string: Creation complete after 1s [id=https://contosokv1weu1dev001.vault.azure.net/secrets/contoso-db-connection-string-dev/e4a7b2c1d3f5489ab0c6d8e2f4a1b3c5]
azurerm_management_lock.db_lock: Creating...
azurerm_management_lock.db_lock: Creation complete after 2s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.DBforPostgreSQL/flexibleServers/contoso-psql-weu1-dev-001/providers/Microsoft.Authorization/locks/contoso-psql-weu1-dev-001-lock]

Apply complete! Resources: 5 added, 0 changed, 0 destroyed.
</Terraform_Plan>`;

const RESPONSE_APPLY_CREATE = `<main.tf>
resource "google_compute_network" "vpc" {
  name                    = "vpc-contoso-dev"
  auto_create_subnetworks = false
  project                 = var.project_id
}

resource "google_compute_subnetwork" "subnet_app" {
  name          = "snet-app-dev"
  ip_cidr_range = "10.0.1.0/24"
  region        = var.region
  network       = google_compute_network.vpc.id
  project       = var.project_id

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
  }
}

resource "google_compute_firewall" "allow_internal" {
  name    = "fw-allow-internal-dev"
  network = google_compute_network.vpc.name
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  source_ranges = ["10.0.0.0/8"]
}

resource "google_cloud_run_v2_service" "api" {
  name     = "contoso-api-dev"
  location = var.region
  project  = var.project_id

  template {
    containers {
      image = "gcr.io/\${var.project_id}/contoso-api:latest"
      resources {
        limits = {
          cpu    = "2"
          memory = "1Gi"
        }
      }
      ports {
        container_port = 8000
      }
    }
    scaling {
      min_instance_count = 1
      max_instance_count = 5
    }
  }
}
</main.tf>
<variables.tf>
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "europe-west1"
}
</variables.tf>
<Terraform_Plan>
google_compute_network.vpc: Creating...
google_compute_network.vpc: Creation complete after 12s [id=projects/contoso-dev-001/global/networks/vpc-contoso-dev]
google_compute_subnetwork.subnet_app: Creating...
google_compute_subnetwork.subnet_app: Creation complete after 8s [id=projects/contoso-dev-001/regions/europe-west1/subnetworks/snet-app-dev]
google_compute_firewall.allow_internal: Creating...
google_compute_firewall.allow_internal: Creation complete after 5s [id=projects/contoso-dev-001/global/firewalls/fw-allow-internal-dev]
google_cloud_run_v2_service.api: Creating...
google_cloud_run_v2_service.api: Still creating... [10s elapsed]
google_cloud_run_v2_service.api: Creation complete after 18s [id=projects/contoso-dev-001/locations/europe-west1/services/contoso-api-dev]

Apply complete! Resources: 4 added, 0 changed, 0 destroyed.
</Terraform_Plan>`;

const RESPONSE_APPLY_CREATE_UPDATE = `<main.tf>
resource "azurerm_app_service_plan" "plan" {
  name                = "asp-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  os_type             = "Linux"
  sku_name            = "P1v3"
}

resource "azurerm_linux_web_app" "webapp" {
  name                = "app-contoso-dev"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_app_service_plan.plan.id

  site_config {
    application_stack {
      node_version = "20-lts"
    }
    always_on = true
  }
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosodev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  https_traffic_only_enabled = true
}

resource "azurerm_key_vault" "kv" {
  name                       = "kv-contoso-dev"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
}
</main.tf>
<Terraform_Plan>
azurerm_app_service_plan.plan: Creating...
azurerm_app_service_plan.plan: Creation complete after 15s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Web/serverFarms/asp-contoso-dev]
azurerm_linux_web_app.webapp: Creating...
azurerm_linux_web_app.webapp: Still creating... [10s elapsed]
azurerm_linux_web_app.webapp: Creation complete after 22s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Web/sites/app-contoso-dev]
azurerm_storage_account.sa: Modifying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/stcontosodev001]
azurerm_storage_account.sa: Modifications complete after 3s
azurerm_key_vault.kv: Modifying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.KeyVault/vaults/kv-contoso-dev]
azurerm_key_vault.kv: Modifications complete after 5s

Apply complete! Resources: 2 added, 2 changed, 0 destroyed.
</Terraform_Plan>`;

const RESPONSE_APPLY_DESTROY = `<Terraform_Plan>
azurerm_container_group.staging_api: Destroying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-staging/providers/Microsoft.ContainerInstance/containerGroups/ci-staging-api]
azurerm_container_group.staging_api: Destruction complete after 30s
azurerm_cosmosdb_account.staging_db: Destroying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-staging/providers/Microsoft.DocumentDB/databaseAccounts/cosmos-staging-001]
azurerm_cosmosdb_account.staging_db: Still destroying... [30s elapsed]
azurerm_cosmosdb_account.staging_db: Destruction complete after 45s
azurerm_redis_cache.staging_cache: Destroying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-staging/providers/Microsoft.Cache/redis/redis-staging-001]
azurerm_redis_cache.staging_cache: Destruction complete after 12s
azurerm_resource_group.staging: Destroying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-staging]
azurerm_resource_group.staging: Still destroying... [1m0s elapsed]
azurerm_resource_group.staging: Destruction complete after 1m15s

Apply complete! Resources: 0 added, 0 changed, 4 destroyed.
</Terraform_Plan>`;

const RESPONSE_APPLY_MIXED = `<main.tf>
resource "azurerm_postgresql_flexible_server" "db" {
  name                   = "psql-contoso-pro"
  resource_group_name    = azurerm_resource_group.rg.name
  location               = azurerm_resource_group.rg.location
  administrator_login    = "contoso_admin"
  version                = "16"
  sku_name               = "GP_Standard_D4s_v3"
  storage_mb             = 131072
  backup_retention_days  = 30
  geo_redundant_backup_enabled = true
  zone                   = "1"
}

resource "azurerm_postgresql_flexible_server_database" "app_db" {
  name      = "contoso_pro"
  server_id = azurerm_postgresql_flexible_server.db.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosopro001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_private_endpoint" "db_pe" {
  name                = "pe-psql-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.endpoints.id

  private_service_connection {
    name                           = "psc-psql-contoso-pro"
    private_connection_resource_id = azurerm_postgresql_flexible_server.db.id
    subresource_names              = ["postgresqlServer"]
    is_manual_connection           = false
  }
}
</main.tf>
<Terraform_Plan>
azurerm_postgresql_flexible_server.db: Creating...
azurerm_postgresql_flexible_server.db: Still creating... [1m0s elapsed]
azurerm_postgresql_flexible_server.db: Still creating... [2m0s elapsed]
azurerm_postgresql_flexible_server.db: Creation complete after 2m34s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-pro/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-contoso-pro]
azurerm_postgresql_flexible_server_database.app_db: Creating...
azurerm_postgresql_flexible_server_database.app_db: Creation complete after 4s [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-pro/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-contoso-pro/databases/contoso_pro]
azurerm_storage_account.sa: Modifying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-pro/providers/Microsoft.Storage/storageAccounts/stcontosopro001]
azurerm_storage_account.sa: Modifications complete after 8s
azurerm_virtual_machine.legacy_worker: Destroying... [id=/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-pro/providers/Microsoft.Compute/virtualMachines/vm-worker-pro]
azurerm_virtual_machine.legacy_worker: Destruction complete after 35s
azurerm_private_endpoint.db_pe: Creating...
azurerm_private_endpoint.db_pe: Still creating... [1m0s elapsed]

Error: creating Private Endpoint (Subscription: "a1b2c3d4" / Resource Group Name: "rg-contoso-pro" / Private Endpoint Name: "pe-psql-contoso-pro"): polling after creation: context deadline exceeded

Apply complete! Resources: 2 added, 1 changed, 1 destroyed.

Note: 1 resource failed to apply. See errors above.
</Terraform_Plan>`;

const RESPONSE_GENERATE_PARTIAL = `<main.tf>
resource "azurerm_resource_group" "rg" {
  name     = "rg-contoso-dev"
  location = var.location

  tags = {
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosodev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_cognitive_account" "openai" {
  name                  = "oai-contoso-dev"
  location              = "swedencentral"
  resource_group_name   = azurerm_resource_group.rg.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "contoso-oai-dev"
}
</main.tf>
<variables.tf>
variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}
</variables.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  + create

Terraform will perform the following actions:

  # azurerm_resource_group.rg will be created
  + resource "azurerm_resource_group" "rg" {
      + id       = (known after apply)
      + location = "westeurope"
      + name     = "rg-contoso-dev"
    }

  # azurerm_storage_account.sa will be created
  + resource "azurerm_storage_account" "sa" {
      + id                        = (known after apply)
      + location                  = "westeurope"
      + name                      = "stcontosodev001"
      + account_replication_type  = "LRS"
      + account_tier              = "Standard"
    }

  # azurerm_cognitive_account.openai will fail validation

Error: creating Cognitive Services Account (Subscription: "a1b2c3d4" / Resource Group Name: "rg-contoso-dev" / Account Name: "oai-contoso-dev"): the SKU "S0" is not available in region "swedencentral" for kind "OpenAI". Available SKUs: none. Request Azure OpenAI access at https://aka.ms/oai/access.

Plan: 2 to add, 0 to change, 0 to destroy. 1 resource failed validation.
</Terraform_Plan>`;

const RESPONSE_GENERATE_MULTI = `<main.tf>
resource "azurerm_resource_group" "rg" {
  name     = "rg-contoso-pro"
  location = var.location

  tags = var.common_tags
}
</main.tf>
<network.tf>
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.0.0.0/16"]
  tags                = var.common_tags
}

resource "azurerm_subnet" "app" {
  name                 = "snet-app"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.1.0/24"]
  service_endpoints    = ["Microsoft.Sql", "Microsoft.Storage", "Microsoft.KeyVault"]
}

resource "azurerm_subnet" "db" {
  name                 = "snet-db"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.2.0/24"]
  delegation {
    name = "psql-delegation"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
    }
  }
}

resource "azurerm_subnet" "pe" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.3.0/24"]
}

resource "azurerm_network_security_group" "app_nsg" {
  name                = "nsg-app-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.common_tags
}

resource "azurerm_subnet_network_security_group_association" "app" {
  subnet_id                 = azurerm_subnet.app.id
  network_security_group_id = azurerm_network_security_group.app_nsg.id
}

resource "azurerm_network_security_group" "db_nsg" {
  name                = "nsg-db-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.common_tags

  security_rule {
    name                       = "AllowPostgreSQL"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "5432"
    source_address_prefix      = "10.0.1.0/24"
    destination_address_prefix = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "db" {
  subnet_id                 = azurerm_subnet.db.id
  network_security_group_id = azurerm_network_security_group.db_nsg.id
}
</network.tf>
<storage.tf>
resource "azurerm_storage_account" "sa" {
  name                     = "stnebpro001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  min_tls_version          = "TLS1_2"

  network_rules {
    default_action             = "Deny"
    virtual_network_subnet_ids = [azurerm_subnet.app.id]
  }

  tags = var.common_tags
}
</storage.tf>
<database.tf>
resource "azurerm_postgresql_flexible_server" "psql" {
  name                          = "psql-contoso-pro"
  resource_group_name           = azurerm_resource_group.rg.name
  location                      = azurerm_resource_group.rg.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.psql.id
  administrator_login           = "contosoadmin"
  administrator_password        = var.db_admin_password
  zone                          = "1"
  storage_mb                    = 65536
  sku_name                      = "GP_Standard_D4s_v3"
  geo_redundant_backup_enabled  = true
  tags                          = var.common_tags
}

resource "azurerm_postgresql_flexible_server_database" "app_db" {
  name      = "contosodb"
  server_id = azurerm_postgresql_flexible_server.psql.id
  charset   = "utf8"
  collation = "en_US.utf8"
}

resource "azurerm_private_dns_zone" "psql" {
  name                = "contoso-pro.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.rg.name
  tags                = var.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "psql" {
  name                  = "psql-dns-link"
  resource_group_name   = azurerm_resource_group.rg.name
  private_dns_zone_name = azurerm_private_dns_zone.psql.name
  virtual_network_id    = azurerm_virtual_network.vnet.id
}
</database.tf>
<keyvault.tf>
resource "azurerm_key_vault" "kv" {
  name                       = "kv-contoso-pro"
  location                   = azurerm_resource_group.rg.location
  resource_group_name        = azurerm_resource_group.rg.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = true
  soft_delete_retention_days = 90
  enable_rbac_authorization  = true

  network_acls {
    default_action             = "Deny"
    bypass                     = "AzureServices"
    virtual_network_subnet_ids = [azurerm_subnet.app.id]
  }

  tags = var.common_tags
}

resource "azurerm_key_vault_secret" "db_connection_string" {
  name         = "db-connection-string"
  value        = "postgresql://\${azurerm_postgresql_flexible_server.psql.administrator_login}@\${azurerm_postgresql_flexible_server.psql.fqdn}:5432/contosodb?sslmode=require"
  key_vault_id = azurerm_key_vault.kv.id
}
</keyvault.tf>
<monitoring.tf>
resource "azurerm_log_analytics_workspace" "law" {
  name                = "law-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = 90
  tags                = var.common_tags
}

resource "azurerm_application_insights" "ai" {
  name                = "ai-contoso-pro"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.law.id
  application_type    = "web"
  tags                = var.common_tags
}
</monitoring.tf>
<variables.tf>
variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westeurope"
}

variable "db_admin_password" {
  description = "PostgreSQL administrator password"
  type        = string
  sensitive   = true
}

variable "common_tags" {
  description = "Tags applied to all resources"
  type        = map(string)
  default = {
    environment = "pro"
    managed_by  = "terraform"
    project     = "contoso"
    cost_center = "platform-engineering"
  }
}
</variables.tf>
<outputs.tf>
output "resource_group_name" {
  value = azurerm_resource_group.rg.name
}

output "storage_account_id" {
  value = azurerm_storage_account.sa.id
}

output "postgresql_fqdn" {
  value     = azurerm_postgresql_flexible_server.psql.fqdn
  sensitive = true
}

output "key_vault_uri" {
  value = azurerm_key_vault.kv.vault_uri
}

output "app_insights_connection_string" {
  value     = azurerm_application_insights.ai.connection_string
  sensitive = true
}
</outputs.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  + create

Terraform will perform the following actions:

  # azurerm_resource_group.rg will be created
  # azurerm_virtual_network.vnet will be created
  # azurerm_subnet.app will be created
  # azurerm_subnet.db will be created
  # azurerm_subnet.pe will be created
  # azurerm_network_security_group.app_nsg will be created
  # azurerm_subnet_network_security_group_association.app will be created
  # azurerm_network_security_group.db_nsg will be created
  # azurerm_subnet_network_security_group_association.db will be created
  # azurerm_storage_account.sa will be created
  # azurerm_postgresql_flexible_server.psql will be created
  # azurerm_postgresql_flexible_server_database.app_db will be created
  # azurerm_private_dns_zone.psql will be created
  # azurerm_private_dns_zone_virtual_network_link.psql will be created
  # azurerm_key_vault.kv will be created
  # azurerm_key_vault_secret.db_connection_string will be created
  # azurerm_log_analytics_workspace.law will be created
  # azurerm_application_insights.ai will be created

Plan: 20 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + resource_group_name          = "rg-contoso-pro"
  + storage_account_id           = (known after apply)
  + postgresql_fqdn              = (sensitive value)
  + key_vault_uri                = (known after apply)
  + app_insights_connection_string = (sensitive value)
</Terraform_Plan>`;

const RESPONSE_DRIFT_FAILED = `<Terraform_Plan>
Initializing the backend...

Error: Error acquiring the state lock

Error message: ConditionalCheckFailedException: The conditional request failed
Lock Info:
  ID:        a1b2c3d4-e5f6-7890-abcd-ef1234567890
  Path:      contoso-terraform-state/dev/terraform.tfstate
  Operation: OperationTypePlan
  Who:       ci-runner@contoso-ci-agent
  Version:   1.9.2
  Created:   2026-06-21 14:32:18.123456 +0000 UTC
  Info:

Terraform acquires a state lock to protect the state from being written
by multiple users at the same time. Please resolve the issue above and try
again. For most commands, you can disable locking with the "-lock=false"
flag, but this is not recommended.
</Terraform_Plan>`;

const RESPONSE_DRIFT_PARTIAL = `<network.tf>
resource "azurerm_network_security_group" "nsg" {
  name                = "nsg-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/8"
    destination_address_prefix = "*"
  }
}

resource "azurerm_storage_account" "sa" {
  name                     = "stcontosodev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}
</network.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  ~ update in-place

Terraform will perform the following actions:

  # azurerm_storage_account.sa will be updated in-place
  ~ resource "azurerm_storage_account" "sa" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/stcontosodev001"
        name                     = "stcontosodev001"
      ~ account_tier             = "Premium" -> "Standard"
    }

  # azurerm_network_security_group.nsg will be updated in-place
  ~ resource "azurerm_network_security_group" "nsg" {
        id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/networkSecurityGroups/nsg-contoso-dev"
        name                = "nsg-contoso-dev"
      ~ security_rule       = [
          ~ {
                name                       = "AllowHTTPS"
              ~ source_address_prefix      = "*" -> "10.0.0.0/8"
            },
        ]
    }

  # azurerm_key_vault.kv cannot be updated — dependency conflict
  Error: updating Key Vault "kv-contoso-dev": the vault has an active private endpoint connection that prevents modification of the network ACLs. Remove the private endpoint or update it separately.

Plan: 0 to add, 2 to change, 0 to destroy. 1 resource skipped due to errors.
</Terraform_Plan>`;

const RESPONSE_PARTIAL_DRIFT = `<storage.tf>
resource "azurerm_storage_account" "sa_hot" {
  name                     = "stcontosohotdev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  access_tier              = "Hot"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_account" "sa_archive" {
  name                     = "stcontosoarchdev001"
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "GRS"
  access_tier              = "Cool"
  min_tls_version          = "TLS1_2"
}
</storage.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  ~ update in-place

Terraform will perform the following actions:

  # azurerm_storage_account.sa_hot will be updated in-place
  ~ resource "azurerm_storage_account" "sa_hot" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/stcontosohotdev001"
        name                     = "stcontosohotdev001"
      ~ min_tls_version          = "TLS1_0" -> "TLS1_2"
    }

  # azurerm_storage_account.sa_archive will be updated in-place
  ~ resource "azurerm_storage_account" "sa_archive" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Storage/storageAccounts/stcontosoarchdev001"
        name                     = "stcontosoarchdev001"
      ~ account_replication_type = "LRS" -> "GRS"
    }

Plan: 0 to add, 2 to change, 0 to destroy.
</Terraform_Plan>`;

const RESPONSE_PARTIAL_DRIFT_FAILED = `<Terraform_Plan>
Initializing the backend...
Initializing provider plugins...

Error: Failed to query available provider packages

Could not retrieve the list of available versions for provider
hashicorp/azurerm: could not connect to registry.terraform.io:
net/http: request canceled while waiting for connection
(Client.Timeout exceeded while awaiting headers)

This may indicate a network connectivity issue. Check your proxy settings
and DNS configuration, or retry after verifying network access to the
Terraform Registry.
</Terraform_Plan>`;

const RESPONSE_PARTIAL_DRIFT_PARTIAL = `<network.tf>
resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = ["10.0.0.0/16"]
}

resource "azurerm_subnet" "app" {
  name                 = "snet-app-dev"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_network_security_group" "nsg" {
  name                = "nsg-contoso-dev"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name

  security_rule {
    name                       = "AllowHTTPS"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "443"
    source_address_prefix      = "10.0.0.0/8"
    destination_address_prefix = "*"
  }
}
</network.tf>
<Terraform_Plan>
Terraform used the selected providers to generate the following execution plan.
Resource actions are indicated with the following symbols:
  ~ update in-place

Terraform will perform the following actions:

  # azurerm_virtual_network.vnet will be updated in-place
  ~ resource "azurerm_virtual_network" "vnet" {
        id                = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/virtualNetworks/vnet-contoso-dev"
        name              = "vnet-contoso-dev"
      ~ address_space     = [
            "10.0.0.0/16",
          - "172.16.0.0/12",
        ]
    }

  # azurerm_subnet.app will be updated in-place
  ~ resource "azurerm_subnet" "app" {
        id                   = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/virtualNetworks/vnet-contoso-dev/subnets/snet-app-dev"
        name                 = "snet-app-dev"
      ~ address_prefixes     = [
          - "10.0.1.0/23",
          + "10.0.1.0/24",
        ]
    }

  # azurerm_network_security_group.nsg cannot be updated
  Error: updating NSG "nsg-contoso-dev": Azure Policy "Deny-NSG-Modification" prevents changes to network security groups in subscription "a1b2c3d4". Contact your Azure administrator to request a policy exemption.

Plan: 0 to add, 2 to change, 0 to destroy. 1 resource blocked by policy.
</Terraform_Plan>`;

const RESPONSE_IMPORT_FAILED = `<imports.tf>
import {
  to = azurerm_resource_group.legacy
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod"
}

import {
  to = azurerm_key_vault.legacy_kv
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.KeyVault/vaults/kv-legacy-prod"
}
</imports.tf>
<Terraform_Plan>
Terraform will perform the following actions:

  # azurerm_resource_group.legacy will be imported
    resource "azurerm_resource_group" "legacy" {
        id       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod"
        location = "northeurope"
        name     = "rg-legacy-prod"
    }

  # azurerm_key_vault.legacy_kv cannot be imported

Error: importing Key Vault "kv-legacy-prod": authorization failed.
The current service principal does not have "Microsoft.KeyVault/vaults/read"
permission on subscription "a1b2c3d4". Assign the "Key Vault Reader" role
or a custom role with the required data-plane permissions.

Import failed. 1 resource imported, 1 resource failed.
</Terraform_Plan>`;

const RESPONSE_IMPORT_PARTIAL = `<imports.tf>
import {
  to = azurerm_resource_group.legacy
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod"
}

import {
  to = azurerm_storage_account.legacy_sa
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.Storage/storageAccounts/stlegacyprod"
}

import {
  to = azurerm_key_vault.legacy_kv
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.KeyVault/vaults/kv-legacy-prod"
}

import {
  to = azurerm_postgresql_flexible_server.legacy_db
  id = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-legacy-prod/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-legacy-prod"
}
</imports.tf>
<resources.tf>
resource "azurerm_resource_group" "legacy" {
  name     = "rg-legacy-prod"
  location = "northeurope"

  tags = {
    managed_by  = "terraform"
    imported_at = "2026-06-22"
  }
}

resource "azurerm_storage_account" "legacy_sa" {
  name                     = "stlegacyprod"
  resource_group_name      = azurerm_resource_group.legacy.name
  location                 = azurerm_resource_group.legacy.location
  account_tier             = "Standard"
  account_replication_type = "GRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_key_vault" "legacy_kv" {
  name                     = "kv-legacy-prod"
  location                 = azurerm_resource_group.legacy.location
  resource_group_name      = azurerm_resource_group.legacy.name
  tenant_id                = data.azurerm_client_config.current.tenant_id
  sku_name                 = "standard"
  purge_protection_enabled = true
}

resource "azurerm_postgresql_flexible_server" "legacy_db" {
  name                   = "psql-legacy-prod"
  resource_group_name    = azurerm_resource_group.legacy.name
  location               = azurerm_resource_group.legacy.location
  administrator_login    = "contoso_admin"
  version                = "16"
  sku_name               = "GP_Standard_D2s_v3"
  storage_mb             = 65536
}
</resources.tf>
<Terraform_Plan>
Terraform will perform the following actions:

  # azurerm_resource_group.legacy will be imported
    resource "azurerm_resource_group" "legacy" {
        id       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod"
        location = "northeurope"
        name     = "rg-legacy-prod"
    }

  # azurerm_storage_account.legacy_sa will be imported
    resource "azurerm_storage_account" "legacy_sa" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod/providers/Microsoft.Storage/storageAccounts/stlegacyprod"
        name                     = "stlegacyprod"
        account_tier             = "Standard"
        account_replication_type = "GRS"
    }

  # azurerm_key_vault.legacy_kv will be imported
    resource "azurerm_key_vault" "legacy_kv" {
        id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-legacy-prod/providers/Microsoft.KeyVault/vaults/kv-legacy-prod"
        name                     = "kv-legacy-prod"
        sku_name                 = "standard"
    }

  # azurerm_postgresql_flexible_server.legacy_db failed to import

Error: importing PostgreSQL Flexible Server "psql-legacy-prod": the server uses
an unsupported configuration for import. The server has "pgbouncer" connection
pooling enabled which requires manual state manipulation. Run
"terraform import azurerm_postgresql_flexible_server.legacy_db <id>" manually
with the -var="pgbouncer_enabled=true" override.

Plan: 3 to import, 0 to add, 0 to change, 0 to destroy. 1 resource failed.
</Terraform_Plan>`;

const RESPONSE_MAP: Record<MockContentType, string> = {
  generate: RESPONSE_GENERATE,
  generate_partial: RESPONSE_GENERATE_PARTIAL,
  generate_multi: RESPONSE_GENERATE_MULTI,
  destructive: RESPONSE_DESTRUCTIVE,
  remove_resource: RESPONSE_REMOVE_RESOURCE,
  drift: RESPONSE_DRIFT,
  drift_failed: RESPONSE_DRIFT_FAILED,
  drift_partial: RESPONSE_DRIFT_PARTIAL,
  partial_drift: RESPONSE_PARTIAL_DRIFT,
  partial_drift_failed: RESPONSE_PARTIAL_DRIFT_FAILED,
  partial_drift_partial: RESPONSE_PARTIAL_DRIFT_PARTIAL,
  import: RESPONSE_IMPORT,
  import_failed: RESPONSE_IMPORT_FAILED,
  import_partial: RESPONSE_IMPORT_PARTIAL,
  apply: RESPONSE_APPLY,
  apply_create: RESPONSE_APPLY_CREATE,
  apply_create_update: RESPONSE_APPLY_CREATE_UPDATE,
  apply_destroy: RESPONSE_APPLY_DESTROY,
  apply_mixed: RESPONSE_APPLY_MIXED,
};

// ─── Terraform Plan (standalone field, used by admin views) ───

const PLAN_TEXT: Record<MockContentType, string> = {
  generate: "Plan: 2 to add, 1 to change, 0 to destroy.",
  generate_partial:
    "Plan: 2 to add, 0 to change, 0 to destroy. 1 resource failed validation.",
  generate_multi: "Plan: 20 to add, 0 to change, 0 to destroy.",
  destructive: "Plan: 4 to add, 0 to change, 3 to destroy.",
  remove_resource: "Plan: 0 to add, 0 to change, 3 to destroy.",
  drift: "Plan: 0 to add, 3 to change, 0 to destroy.",
  drift_failed: "Error: Error acquiring the state lock.",
  drift_partial:
    "Plan: 0 to add, 2 to change, 0 to destroy. 1 resource skipped due to errors.",
  partial_drift: "Plan: 0 to add, 2 to change, 0 to destroy.",
  partial_drift_failed:
    "Error: Failed to query available provider packages.",
  partial_drift_partial:
    "Plan: 0 to add, 2 to change, 0 to destroy. 1 resource blocked by policy.",
  import: "Plan: 4 to import, 0 to add, 0 to change, 0 to destroy.",
  import_failed: "Import failed. 1 resource imported, 1 resource failed.",
  import_partial:
    "Plan: 3 to import, 0 to add, 0 to change, 0 to destroy. 1 resource failed.",
  apply:
    "Apply complete! Resources: 5 added, 0 changed, 0 destroyed.",
  apply_create:
    "Apply complete! Resources: 4 added, 0 changed, 0 destroyed.",
  apply_create_update:
    "Apply complete! Resources: 2 added, 2 changed, 0 destroyed.",
  apply_destroy:
    "Apply complete! Resources: 0 added, 0 changed, 4 destroyed.",
  apply_mixed:
    "Apply complete! Resources: 2 added, 1 changed, 1 destroyed. 1 resource failed.",
};

// ─── Conversation History ─────────────────────────────────────

interface ConversationPair {
  user: string;
  assistant: string;
}

const HISTORY: Record<MockContentType, ConversationPair> = {
  generate: {
    user: "Create a storage account in Azure with a resource group in West Europe",
    assistant:
      "I've generated the Terraform code for an Azure resource group and storage account in the West Europe region. The storage account uses Standard LRS replication with a 7-day soft delete retention policy.",
  },
  generate_partial: {
    user: "Create a storage account, resource group, and Azure OpenAI service in dev",
    assistant:
      "I've generated the Terraform code for 3 resources, but 1 failed validation. The resource group and storage account were validated successfully. However, the Azure OpenAI Cognitive Services account failed — the SKU 'S0' is not available in the 'swedencentral' region. You may need to request Azure OpenAI access or choose a different region.",
  },
  generate_multi: {
    user: "Set up the complete production infrastructure for the Contoso platform on Azure — networking, database, storage, key vault, and monitoring",
    assistant:
      "I've generated 20 resources across 7 Terraform files for the full Contoso production stack. This includes a VNet with 3 subnets (app, database, private endpoints), NSGs with least-privilege rules, a ZRS storage account with network restrictions, a PostgreSQL 16 flexible server with geo-redundant backup and private DNS, a Key Vault with RBAC authorization and purge protection, and a Log Analytics workspace with Application Insights. The database connection string is stored as a Key Vault secret. All resources are tagged consistently and follow Azure naming conventions.",
  },
  destructive: {
    user: "Migrate the backend from Virtual Machines to Azure Container Instances",
    assistant:
      "I've generated the Terraform code to migrate your backend from VM-based to container-based architecture. This will create an Azure Container Group and Container Registry, and remove the existing VM and load balancer. The NSG rules will be replaced to allow container port 8000 instead of SSH.",
  },
  remove_resource: {
    user: "Remove the legacy ETL data factory and its export storage account from the pro environment",
    assistant:
      "I've removed the legacy ETL stack from the configuration: the Data Factory 'adf-legacy-etl-pro', the GRS export storage account 'stetlexportspro' and the 'etl-connection' Key Vault secret. Nothing is created or replaced — the plan destroys 3 resources and drops the two outputs that referenced them. The data lake storage account and its resource group are untouched. Because this deletes data permanently, applying it needs an operator to unblock the session first.",
  },
  drift: {
    user: "Detect and remediate drift in my Azure networking configuration",
    assistant:
      "I've detected 3 drifted resources in your networking setup. The storage account tier was changed from Standard to Premium in the portal, an extra address space was added to the VNet, and the NSG HTTPS rule source was opened to all. I've generated remediation code to restore the desired state.",
  },
  drift_failed: {
    user: "Detect and fix drift in the dev environment infrastructure",
    assistant:
      "Drift detection failed. Terraform could not acquire the state lock — another operation (a CI plan run by ci-runner@contoso-ci-agent) is currently holding the lock. Wait for that operation to complete or manually release the lock before retrying.",
  },
  drift_partial: {
    user: "Remediate all drifted resources in the dev networking stack",
    assistant:
      "I remediated 2 of 3 drifted resources. The storage account tier was reverted from Premium to Standard, and the NSG HTTPS rule source was restricted back to 10.0.0.0/8. However, the Key Vault network ACL update was blocked by an active private endpoint connection — you'll need to modify the private endpoint configuration first.",
  },
  partial_drift: {
    user: "Check for drift on the storage accounts only in dev",
    assistant:
      "I scanned the storage accounts in the dev environment and found 2 drifted resources. The hot storage account had its TLS version downgraded to 1.0 in the portal, and the archive storage account replication was changed from GRS to LRS. Both have been remediated — TLS is back to 1.2 and replication is restored to GRS.",
  },
  partial_drift_failed: {
    user: "Check for drift on the networking resources in dev",
    assistant:
      "Partial drift detection failed. Terraform could not connect to the provider registry (registry.terraform.io) to download the required azurerm provider. This indicates a network connectivity issue — check your proxy settings, DNS configuration, or firewall rules and retry.",
  },
  partial_drift_partial: {
    user: "Check and fix drift on the VNet, subnet, and NSG in dev",
    assistant:
      "I checked 3 networking resources and remediated 2 of them. The VNet had an extra 172.16.0.0/12 address space added outside Terraform, which was removed. The app subnet CIDR was expanded from /24 to /23 in the portal and has been restored. However, the NSG rule update was blocked by Azure Policy 'Deny-NSG-Modification' — contact your Azure administrator to request a policy exemption.",
  },
  import: {
    user: "Import existing Azure resources from resource group rg-legacy-prod into Terraform",
    assistant:
      "I've generated import blocks and resource definitions for 4 resources found in rg-legacy-prod: the resource group itself, a storage account (stlegacyprod), a key vault (kv-legacy-prod), and a PostgreSQL flexible server (psql-legacy-prod). All resources will be imported without any infrastructure changes.",
  },
  import_failed: {
    user: "Import the resource group and key vault from rg-legacy-prod",
    assistant:
      "Import failed. The resource group was imported successfully, but the Key Vault import failed due to insufficient permissions — the current service principal lacks the 'Microsoft.KeyVault/vaults/read' permission. Assign the 'Key Vault Reader' role to the service principal and retry.",
  },
  import_partial: {
    user: "Import all resources from rg-legacy-prod into Terraform management",
    assistant:
      "3 of 4 resources were imported successfully: the resource group, storage account, and key vault. The PostgreSQL flexible server import failed because it uses pgbouncer connection pooling, which requires manual state manipulation. Run the import command manually with the pgbouncer override flag.",
  },
  apply: {
    user: "Deploy the PostgreSQL database, storage account, and supporting infrastructure for the Contoso dev environment",
    assistant:
      "All 5 resources have been deployed successfully. The PostgreSQL 16 flexible server and database are provisioned in West Europe with zone-redundant availability. A ZRS storage account is created with TLS 1.2 enforcement and 7-day soft delete retention. The database connection string is securely stored in Key Vault, and a CanNotDelete management lock protects the database server from accidental removal.",
  },
  apply_create: {
    user: "Deploy the new API infrastructure on GCP",
    assistant:
      "All 4 resources have been created successfully. The VPC network, subnet, firewall rule, and Cloud Run service are now provisioned in europe-west1. The API is reachable at the Cloud Run service URL.",
  },
  apply_create_update: {
    user: "Add the web app and harden the existing storage and key vault",
    assistant:
      "2 new resources created (App Service plan and Linux web app) and 2 existing resources updated (storage account TLS enforcement, key vault purge protection). All operations completed without errors.",
  },
  apply_destroy: {
    user: "Tear down the staging environment completely",
    assistant:
      "The staging environment has been fully decommissioned. 4 resources destroyed: container group, Cosmos DB account, Redis cache, and the resource group. All data has been permanently deleted.",
  },
  apply_mixed: {
    user: "Migrate the database to PostgreSQL and clean up the legacy worker VM",
    assistant:
      "Migration partially completed. The PostgreSQL server and database were created, storage replication was upgraded to ZRS, and the legacy VM was removed. However, the private endpoint creation failed due to subnet IP exhaustion — manual intervention is needed.",
  },
};

// ─── Reports ──────────────────────────────────────────────────

function createGenerateReport(): TerraformReport {
  return {
    status: "Succeeded",
    summary: {
      create: 2,
      update: 1,
      delete: 0,
      recreate: 0,
    },
    detailed_changes: [
      {
        action: "create",
        name: "Resource Group & Storage Account",
        summary: "Creates a resource group in West Europe and a standard LRS storage account with soft delete enabled for blob and file storage.",
        notes: "Creates 2 new foundational resources for the Contoso project.",
        details:
          '# azurerm_resource_group.rg will be created\n+ resource "azurerm_resource_group" "rg" {\n    + id       = (known after apply)\n    + location = "westeurope"\n    + name     = "rg-contoso-dev"\n    + tags     = {\n        + "environment" = "dev"\n        + "managed_by"  = "terraform"\n      }\n  }\n\n# azurerm_storage_account.sa will be created\n+ resource "azurerm_storage_account" "sa" {\n    + access_tier               = (known after apply)\n    + id                        = (known after apply)\n    + location                  = "westeurope"\n    + min_tls_version           = "TLS1_2"\n    + name                      = "stcontosodev001"\n    + resource_group_name       = "rg-contoso-dev"\n    + account_replication_type  = "LRS"\n    + account_tier              = "Standard"\n    + tags                      = {\n        + "environment" = "dev"\n      }\n  }',
      },
      {
        action: "update",
        name: "Virtual Network Address Space",
        summary: "Updates the virtual network to include an additional 10.1.0.0/24 address space for the new container subnet.",
        notes: "Non-destructive network change adding a new subnet range.",
        details:
          '# azurerm_virtual_network.vnet will be updated in-place\n~ resource "azurerm_virtual_network" "vnet" {\n      id                = "/subscriptions/a1b2c3d4-e5f6-7890-abcd-ef1234567890/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/virtualNetworks/vnet-contoso-dev"\n      name              = "vnet-contoso-dev"\n    ~ address_space     = [\n          "10.0.0.0/16",\n        + "10.1.0.0/24",\n      ]\n  }',
      },
    ],
    potential_impact: {
      banner: {
        level: "low",
        title: "Low Risk: Additive Infrastructure Changes",
        description: "This plan creates new resources and adds an address space to an existing virtual network. These are non-disruptive additions that do not affect running resources.",
      },
      summary:
        "This plan will create a new resource group and storage account in Azure West Europe, and expand the virtual network address space to include 10.1.0.0/24. The resource group serves as the organizational container for all project resources. The storage account uses Standard LRS replication with TLS 1.2 enforcement and a 7-day soft delete retention policy. The VNet change is additive and does not modify existing subnets or connectivity.",
      bullet_points: [
        {
          title: "Resource Group",
          description:
            "A new resource group 'rg-contoso-dev' will be created in West Europe as the primary container for all Contoso project resources. Resource groups are free metadata containers with no service impact.",
        },
        {
          title: "Storage Account",
          description:
            "A Standard LRS storage account 'stcontosodev001' will be provisioned with TLS 1.2 enforcement and 7-day soft delete for blob data recovery. This enables blob and file storage for the project.",
        },
        {
          title: "Network Expansion",
          description:
            "The existing virtual network 'vnet-contoso-dev' will gain an additional 10.1.0.0/24 address space. This does not affect existing subnets or routes and does not cause service interruption.",
        },
      ],
    },
    estimated_costs: {
      currency: "USD",
      total_fixed_monthly_cost: 21.0,
      introduction_paragraph:
        "Terraform plans don't include direct cost estimation, but based on Azure's public pricing for the West Europe region, the resources being created in this plan have the following estimated costs.",
      breakdown: [
        {
          resource_type: "Azure Storage Account (azurerm_storage_account)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 21.0,
          notes: "Standard LRS storage pricing based on estimated 100 GB stored data and 10,000 monthly transactions. Actual cost depends on usage. Soft delete retention adds minimal overhead for the 7-day window.",
        },
        {
          resource_type: "Azure Resource Group (azurerm_resource_group)",
          pricing_model: "free",
          fixed_monthly_cost: 0.0,
          notes: "Resource groups are a free organizational construct in Azure. There are no charges for creating, maintaining, or using resource groups regardless of the number of resources they contain.",
        },
        {
          resource_type: "Virtual Network Update (azurerm_virtual_network)",
          pricing_model: "free",
          fixed_monthly_cost: 0.0,
          notes: "Adding address space to an existing virtual network incurs no additional cost. Azure VNets are free; charges only apply to VNet peering, VPN gateways, or cross-region data transfer.",
        },
      ],
    },
  };
}

function createDestructiveReport(): TerraformReport {
  return {
    status: "Succeeded",
    summary: {
      create: 3,
      update: 0,
      delete: 2,
      recreate: 1,
    },
    detailed_changes: [
      {
        action: "create",
        name: "Container Infrastructure",
        summary: "Creates the Azure Container Group, Container Registry, and dedicated subnet for the containerized backend deployment. The container group runs the backend API image with 2 vCPU and 4 GB RAM on a private subnet with ACI delegation.",
        notes: "Creates 3 new resources to support the container-based backend architecture.",
        details:
          '# azurerm_container_group.backend will be created\n+ resource "azurerm_container_group" "backend" {\n    + id                  = (known after apply)\n    + ip_address          = (known after apply)\n    + name                = "ci-contoso-backend-dev"\n    + location            = "westeurope"\n    + resource_group_name = "rg-contoso-dev"\n    + os_type             = "Linux"\n    + ip_address_type     = "Private"\n    + subnet_ids          = (known after apply)\n\n    + container {\n        + name   = "api"\n        + image  = "contosoacr.azurecr.io/backend:latest"\n        + cpu    = 2\n        + memory = 4\n\n        + ports {\n            + port     = 8000\n            + protocol = "TCP"\n          }\n      }\n  }\n\n# azurerm_container_registry.acr will be created\n+ resource "azurerm_container_registry" "acr" {\n    + id                  = (known after apply)\n    + login_server        = (known after apply)\n    + name                = "contosoacr"\n    + sku                 = "Standard"\n    + admin_enabled       = false\n  }\n\n# azurerm_subnet.containers will be created\n+ resource "azurerm_subnet" "containers" {\n    + id                   = (known after apply)\n    + name                 = "snet-containers"\n    + address_prefixes     = ["10.0.3.0/24"]\n\n    + delegation {\n        + name = "container-delegation"\n        + service_delegation {\n            + name = "Microsoft.ContainerInstance/containerGroups"\n          }\n      }\n  }',
      },
      {
        action: "delete",
        name: "VM & Load Balancer Decommission",
        summary: "Permanently destroys the backend Virtual Machine (Standard_D2s_v3) and its associated load balancer. These resources are replaced by the container-based architecture. Ensure data migration is complete before applying.",
        notes: "Destroys 2 resources that are superseded by the container deployment.",
        details:
          '# azurerm_virtual_machine.backend will be destroyed\n- resource "azurerm_virtual_machine" "backend" {\n    - id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Compute/virtualMachines/vm-backend-dev" -> null\n    - name                = "vm-backend-dev" -> null\n    - location            = "westeurope" -> null\n    - vm_size             = "Standard_D2s_v3" -> null\n    - os_disk {\n        - caching              = "ReadWrite" -> null\n        - storage_account_type = "Premium_LRS" -> null\n      }\n  }\n\n# azurerm_lb.backend will be destroyed\n- resource "azurerm_lb" "backend" {\n    - id                  = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-dev/providers/Microsoft.Network/loadBalancers/lb-backend-dev" -> null\n    - name                = "lb-backend-dev" -> null\n    - sku                 = "Standard" -> null\n  }',
      },
      {
        action: "recreate",
        name: "Network Security Group Replacement",
        summary: "Replaces the backend NSG to update security rules from SSH access (port 22) to container port access (port 8000). The NSG must be destroyed and recreated because the security rule structure has changed.",
        notes: "NSG replacement requires brief network disruption during recreation.",
        details:
          '# azurerm_network_security_group.backend must be replaced\n-/+ resource "azurerm_network_security_group" "backend" {\n    ~ id                  = "/subscriptions/a1b2c3d4/.../nsg-backend-dev" -> (known after apply)\n      name                = "nsg-backend-dev"\n    ~ security_rule       = [\n        - {\n            - name                       = "AllowSSH"\n            - priority                   = 100\n            - direction                  = "Inbound"\n            - access                     = "Allow"\n            - protocol                   = "Tcp"\n            - destination_port_range     = "22"\n          },\n        + {\n            + name                       = "AllowContainerPort"\n            + priority                   = 100\n            + direction                  = "Inbound"\n            + access                     = "Allow"\n            + protocol                   = "Tcp"\n            + destination_port_range     = "8000"\n          },\n      ]\n  }',
      },
    ],
    potential_impact: {
      banner: {
        level: "high",
        title: "High Impact: VM-to-Container Migration",
        description: "This plan includes resource deletions and a complete service migration from Virtual Machines to Azure Container Instances. Downtime is expected.",
      },
      summary:
        "This plan migrates the backend from a VM-based deployment (Standard_D2s_v3) to Azure Container Instances. The existing virtual machine and load balancer will be permanently deleted, and a new container group, container registry, and dedicated subnet will be created. The network security group will be replaced with updated rules allowing container port 8000 instead of SSH port 22. Ensure all application data has been migrated and DNS records updated before applying these changes.",
      bullet_points: [
        {
          title: "VM Deletion",
          description:
            "The backend VM 'vm-backend-dev' (Standard_D2s_v3) and its managed disks (Premium_LRS) will be permanently destroyed. Any data stored on the VM's OS or data disks will be lost irreversibly.",
        },
        {
          title: "Load Balancer Removal",
          description:
            "The Standard SKU load balancer 'lb-backend-dev' will be removed. ACI uses a private IP directly within the subnet, eliminating the need for a separate load balancer.",
        },
        {
          title: "Service Downtime",
          description:
            "Expect 5-10 minutes of downtime during the migration. The VM is destroyed before the container group is fully provisioned. Consider a blue-green deployment strategy to minimize impact.",
        },
        {
          title: "Security Rule Change",
          description:
            "The NSG 'nsg-backend-dev' will be recreated with inbound rules changing from SSH (port 22) to container access (port 8000). This causes a brief network connectivity interruption during the NSG replacement.",
        },
      ],
    },
    estimated_costs: {
      currency: "USD",
      total_fixed_monthly_cost: -85.0,
      introduction_paragraph:
        "Terraform plans don't include direct cost estimation, but based on Azure's public pricing for the West Europe region, migrating from VMs to containers results in significant compute cost savings. The container registry adds a small fixed cost that is offset by the VM removal.",
      breakdown: [
        {
          resource_type: "Azure Container Group (azurerm_container_group)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 48.0,
          notes: "Based on 2 vCPU and 4 GB RAM running continuously in West Europe. ACI pricing is per-second for vCPU ($0.0000013/s) and memory ($0.0000005/s per GB). Cost may be lower with burst or scheduled workloads.",
        },
        {
          resource_type: "Azure Container Registry (azurerm_container_registry)",
          pricing_model: "fixed",
          fixed_monthly_cost: 5.0,
          notes: "Standard tier with 10 GB included storage and 2 webhooks. Additional storage is billed at $0.667/GB/month. Geo-replication available at additional cost if needed.",
        },
        {
          resource_type: "VM Removal Savings (azurerm_virtual_machine)",
          pricing_model: "fixed",
          fixed_monthly_cost: -138.0,
          notes: "Savings from decommissioning the Standard_D2s_v3 VM instance (2 vCPU, 8 GB RAM) with Premium_LRS managed disk. Includes compute, disk, and associated network costs.",
        },
      ],
    },
  };
}

function createRemoveResourceReport(): TerraformReport {
  return {
    status: "Succeeded",
    summary: {
      create: 0,
      update: 0,
      delete: 3,
      recreate: 0,
    },
    detailed_changes: [
      {
        action: "delete",
        name: "Legacy ETL Data Factory",
        summary:
          "Permanently destroys the Azure Data Factory 'adf-legacy-etl-pro', including its linked services, datasets and pipeline definitions. The nightly ingestion pipeline it ran was superseded by the streaming job, so no schedule is lost — but pipeline run history is not recoverable once the factory is gone.",
        notes: "Destroys 1 resource. Pipeline run history is deleted with the factory.",
        details:
          '# azurerm_data_factory.legacy_etl will be destroyed\n- resource "azurerm_data_factory" "legacy_etl" {\n    - id                     = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-analytics-pro/providers/Microsoft.DataFactory/factories/adf-legacy-etl-pro" -> null\n    - name                   = "adf-legacy-etl-pro" -> null\n    - location               = "westeurope" -> null\n    - resource_group_name    = "rg-contoso-analytics-pro" -> null\n    - public_network_enabled = true -> null\n  }',
      },
      {
        action: "delete",
        name: "ETL Export Storage Account",
        summary:
          "Permanently destroys the storage account 'stetlexportspro' (Standard GRS) and every blob it holds. It currently stores ~1.4 TB of nightly CSV exports. Azure has no undelete for a destroyed storage account, so anything still needed must be copied to the data lake before applying.",
        notes: "Destroys 1 resource. ~1.4 TB of exported data is deleted irreversibly.",
        details:
          '# azurerm_storage_account.etl_exports will be destroyed\n- resource "azurerm_storage_account" "etl_exports" {\n    - id                       = "/subscriptions/a1b2c3d4/resourceGroups/rg-contoso-analytics-pro/providers/Microsoft.Storage/storageAccounts/stetlexportspro" -> null\n    - name                     = "stetlexportspro" -> null\n    - account_tier             = "Standard" -> null\n    - account_replication_type = "GRS" -> null\n    - location                 = "westeurope" -> null\n  }',
      },
      {
        action: "delete",
        name: "ETL Connection Secret",
        summary:
          "Removes the 'etl-connection' secret from Key Vault 'kv-contoso-pro'. The vault has soft delete enabled with a 90-day retention window, so this secret can be recovered if it turns out something still reads it.",
        notes: "Destroys 1 resource. Recoverable for 90 days via Key Vault soft delete.",
        details:
          '# azurerm_key_vault_secret.etl_connection will be destroyed\n- resource "azurerm_key_vault_secret" "etl_connection" {\n    - id           = "https://kv-contoso-pro.vault.azure.net/secrets/etl-connection/9f2c" -> null\n    - name         = "etl-connection" -> null\n    - key_vault_id = "/subscriptions/a1b2c3d4/.../vaults/kv-contoso-pro" -> null\n  }',
      },
    ],
    potential_impact: {
      banner: {
        level: "high",
        title: "High Impact: Permanent Resource Removal",
        description:
          "This plan only destroys. Three production resources — including a storage account holding ~1.4 TB — are deleted with nothing created in their place. Apply is locked until an operator unblocks the session.",
      },
      summary:
        "This plan decommissions the legacy ETL stack in the pro environment. The Data Factory, its GRS export storage account and the Key Vault secret that held its connection string are all destroyed, and the two Terraform outputs that referenced them are dropped. Nothing is created, changed or replaced. The data lake storage account and the analytics resource group are explicitly retained. Confirm the streaming ingestion job has been running cleanly and that any export still needed has been copied to the lake before this is applied — only the Key Vault secret is recoverable afterwards.",
      bullet_points: [
        {
          title: "Irreversible Data Loss",
          description:
            "Destroying 'stetlexportspro' deletes roughly 1.4 TB of nightly CSV exports. The account has no soft delete configured, and GRS replication does not protect against an intentional delete — the secondary region copy goes with it.",
        },
        {
          title: "No Replacement Resources",
          description:
            "Unlike a migration, this plan creates nothing. Any consumer still pointing at the Data Factory or the export container will start failing the moment the apply completes.",
        },
        {
          title: "Downstream Consumers",
          description:
            "Two Terraform outputs ('etl_exports_endpoint' and 'legacy_etl_factory_id') are removed. Any other workspace using them via a remote state data source will fail to plan until it is updated.",
        },
        {
          title: "Partial Recoverability",
          description:
            "Only the 'etl-connection' Key Vault secret can be restored, through the vault's 90-day soft delete window. The Data Factory and the storage account cannot.",
        },
      ],
    },
    estimated_costs: {
      currency: "USD",
      total_fixed_monthly_cost: -212.0,
      introduction_paragraph:
        "Terraform plans don't include direct cost estimation, but based on Azure's public pricing for the West Europe region, removing the legacy ETL stack eliminates its entire monthly spend. The figures below are the recurring costs that stop after this apply.",
      breakdown: [
        {
          resource_type: "Azure Data Factory (azurerm_data_factory)",
          pricing_model: "usage_based",
          fixed_monthly_cost: -96.0,
          notes: "Savings from retiring the nightly pipeline: ~30 pipeline runs/month with 4 activity runs each, plus the self-hosted integration runtime hours. Usage-based, so the actual saving varies with run volume.",
        },
        {
          resource_type: "Storage Account (azurerm_storage_account)",
          pricing_model: "usage_based",
          fixed_monthly_cost: -114.0,
          notes: "Savings from deleting ~1.4 TB of Standard GRS hot blob storage ($0.0435/GB/month with geo-replication), plus the read/write transaction costs of the nightly export job.",
        },
        {
          resource_type: "Key Vault Secret (azurerm_key_vault_secret)",
          pricing_model: "usage_based",
          fixed_monthly_cost: -2.0,
          notes: "Marginal saving on secret retrieval operations ($0.03 per 10,000 transactions). The Key Vault itself is retained and continues to be billed.",
        },
      ],
    },
    recommendations: [
      "Copy any export still required from 'stetlexportspro' into the data lake account before applying — the storage account has no soft delete and the data cannot be recovered afterwards.",
      "Confirm the streaming ingestion job has produced complete daily partitions for at least one full cycle before removing its predecessor.",
      "Search other Terraform workspaces for remote state references to 'etl_exports_endpoint' and 'legacy_etl_factory_id' and update them first.",
      "Ask an operator to unblock apply on this session once the checks above are done; the plan is destroy-only and is locked by default.",
    ],
  };
}

function createDriftReport(): TerraformReport {
  return {
    status: "Succeeded",
    remediation_summary:
      "3 of 3 drifted resources have been remediated. All resources now match the desired Terraform state.",
    remediated_resources: [
      {
        resource_address: "azurerm_storage_account.sa",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "account_tier",
            change_description: "Standard -> Premium (drifted in portal)",
            reason: "Manual change detected in Azure portal",
            details: [
              "Reverted account_tier from Premium back to Standard",
              "Updated Terraform state to match desired config",
            ],
          },
        ],
      },
      {
        resource_address: "azurerm_virtual_network.vnet",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "address_space",
            change_description:
              '["10.0.0.0/16"] -> ["10.0.0.0/16", "10.1.0.0/16"]',
            reason: "Additional address space added outside Terraform",
            details: [
              "Removed extra 10.1.0.0/16 address space that was added via portal",
              "VNet now matches the single 10.0.0.0/16 defined in Terraform",
            ],
          },
        ],
      },
      {
        resource_address: "azurerm_network_security_group.nsg",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "security_rule[AllowHTTPS].source_address_prefix",
            change_description: '"*" -> "10.0.0.0/8"',
            reason: "NSG rule was relaxed to allow all inbound HTTPS traffic",
            details: [
              "Restored source_address_prefix to 10.0.0.0/8 (internal only)",
              "Added DenyAll rule at priority 4096 as explicit fallback",
            ],
          },
        ],
      },
    ],
  };
}

function createImportReport(): TerraformReport {
  return {
    status: "Succeeded",
    import_summary: {
      total_untracked_resources: 5,
      successfully_imported_count: 4,
      not_imported_count: 1,
      resource_group_name: "rg-legacy-prod",
    },
    resource_details: [
      {
        category: "Compute",
        resource_identifier:
          "azurerm_resource_group.legacy (rg-legacy-prod)",
        details: "Resource group in northeurope with no tags",
      },
      {
        category: "Storage",
        resource_identifier:
          "azurerm_storage_account.legacy_sa (stlegacyprod)",
        details:
          "Standard GRS storage account with TLS 1.2, 2.3 TB used",
      },
      {
        category: "Security",
        resource_identifier:
          "azurerm_key_vault.legacy_kv (kv-legacy-prod)",
        details:
          "Standard tier key vault with purge protection, 12 secrets stored",
      },
      {
        category: "Database",
        resource_identifier:
          "azurerm_postgresql_flexible_server.legacy_db (psql-legacy-prod)",
        details:
          "PostgreSQL 16 on GP_Standard_D2s_v3, 64 GB storage, geo-redundant backup",
      },
    ],
    recommendations: [
      "Review imported resource tags and add consistent tagging",
      "Enable diagnostic settings on the key vault for audit logging",
      "Consider upgrading storage account replication from GRS to RA-GRS for read access in secondary region",
      "A Log Analytics workspace was detected but not imported — it may be shared across resource groups",
    ],
  };
}

function createApplyReport(): TerraformReport {
  return {
    status: "Success",
    apply_summary: {
      total_resources: 5,
      created: 5,
      updated: 0,
      destroyed: 0,
      failed: 0,
    },
    execution_summary:
      "The Terraform apply operation completed successfully in approximately 2 minutes and 26 seconds. All 5 planned resources were created without errors. The deployment provisioned a PostgreSQL 16 Flexible Server (contoso-psql-weu1-dev-001) with a dedicated application database, a zone-redundant storage account (contososaweu1dev001), and supporting security infrastructure including a Key Vault secret for the database connection string and a CanNotDelete management lock on the database server. All resources were created in the data-contoso-rsg-weu1-dev resource group within the West Europe region.",
    resource_changes: [
      {
        resource_type: "azurerm_postgresql_flexible_server",
        resource_name: "db",
        action: "created",
        status: "success",
        details:
          "Created PostgreSQL 16 Flexible Server 'contoso-psql-weu1-dev-001' in West Europe (Zone 1) with GP_Standard_D2s_v3 SKU (2 vCPUs, 8 GiB RAM). Configured with 64 GB storage, 14-day backup retention, and administrator login 'contoso_admin'. The server is provisioned in the data-contoso-rsg-weu1-dev resource group with tags for environment (dev), project (contoso), and managed_by (terraform). Creation took 1 minute and 52 seconds.",
      },
      {
        resource_type: "azurerm_postgresql_flexible_server_database",
        resource_name: "app",
        action: "created",
        status: "success",
        details:
          "Created database 'contoso_dev' on server 'contoso-psql-weu1-dev-001' with UTF-8 character set and en_US.utf8 collation. This is the primary application database for the Contoso dev environment. Creation completed in 3 seconds.",
      },
      {
        resource_type: "azurerm_storage_account",
        resource_name: "sa",
        action: "created",
        status: "success",
        details:
          "Created Standard ZRS StorageV2 account 'contososaweu1dev001' in West Europe with strict security settings: HTTPS-only traffic enforced, TLS 1.2 minimum version. Blob retention policies configured with 7-day soft delete for both blobs and containers. Zone-redundant storage (ZRS) provides resilience against single-zone failures. Tagged with environment=dev, project=contoso, managed_by=terraform. Creation took 28 seconds.",
      },
      {
        resource_type: "azurerm_key_vault_secret",
        resource_name: "db_connection_string",
        action: "created",
        status: "success",
        details:
          "Stored the PostgreSQL connection string as secret 'contoso-db-connection-string-dev' in Key Vault 'contosokv1weu1dev001'. The connection string includes the server FQDN, administrator credentials, database name, and enforces SSL mode (sslmode=require). Secret version: e4a7b2c1d3f5489ab0c6d8e2f4a1b3c5. This enables secure retrieval of database credentials by authorized applications without exposing them in configuration files. Creation completed in 1 second.",
      },
      {
        resource_type: "azurerm_management_lock",
        resource_name: "db_lock",
        action: "created",
        status: "success",
        details:
          "Applied a 'CanNotDelete' management lock named 'contoso-psql-weu1-dev-001-lock' to the PostgreSQL Flexible Server to prevent accidental deletion. Lock note: 'Critical database — prevent accidental deletion'. This is a protection mechanism ensuring the database cannot be removed without first removing the lock, even by users with Owner or Contributor roles. Creation completed in 2 seconds.",
      },
    ],
    recommendations: [
      "Configure firewall rules on the PostgreSQL server to restrict access to known application subnets and deny public network access",
      "Run a full 'terraform plan' without the -target option to ensure no other pending changes exist in the configuration",
      "Set up Azure Monitor diagnostic settings on the PostgreSQL server for query performance insights and audit logging",
      "Verify that the Key Vault access policies allow the application service principal to retrieve the stored connection string secret",
      "Consider enabling geo-redundant backup on the PostgreSQL server for disaster recovery in production environments",
      "Review the 7-day blob retention policy on the storage account to ensure it meets data recovery requirements for the dev environment",
      "Test application connectivity to the PostgreSQL server using the connection string from Key Vault before routing live traffic",
    ],
  };
}

function createApplyCreateReport(): TerraformReport {
  return {
    status: "Success",
    apply_summary: {
      total_resources: 4,
      created: 4,
      updated: 0,
      destroyed: 0,
      failed: 0,
    },
    execution_summary:
      "All 4 resources were created successfully in GCP europe-west1. Total execution time: 43 seconds.",
    resource_changes: [
      {
        resource_type: "google_compute_network",
        resource_name: "vpc",
        action: "created",
        status: "success",
        details: "VPC network 'vpc-contoso-dev' created with auto subnets disabled",
      },
      {
        resource_type: "google_compute_subnetwork",
        resource_name: "subnet_app",
        action: "created",
        status: "success",
        details: "Subnet 'snet-app-dev' (10.0.1.0/24) provisioned in europe-west1 with flow logs enabled",
      },
      {
        resource_type: "google_compute_firewall",
        resource_name: "allow_internal",
        action: "created",
        status: "success",
        details: "Firewall rule 'fw-allow-internal-dev' created allowing internal traffic (10.0.0.0/8) on all TCP ports",
      },
      {
        resource_type: "google_cloud_run_v2_service",
        resource_name: "api",
        action: "created",
        status: "success",
        details: "Cloud Run service 'contoso-api-dev' deployed with 2 vCPU, 1Gi memory, scaling 1-5 instances",
      },
    ],
    recommendations: [
      "Configure a custom domain and SSL certificate for the Cloud Run service",
      "Set up Cloud Armor security policies to protect the API endpoint",
      "Enable VPC connector for the Cloud Run service to access resources in the private subnet",
    ],
  };
}

function createApplyCreateUpdateReport(): TerraformReport {
  return {
    status: "Success",
    apply_summary: {
      total_resources: 4,
      created: 2,
      updated: 2,
      destroyed: 0,
      failed: 0,
    },
    execution_summary:
      "2 resources created and 2 updated successfully. Total execution time: 45 seconds. Security posture improved on existing resources.",
    resource_changes: [
      {
        resource_type: "azurerm_app_service_plan",
        resource_name: "plan",
        action: "created",
        status: "success",
        details: "App Service plan 'asp-contoso-dev' created with P1v3 SKU (Linux) in westeurope",
      },
      {
        resource_type: "azurerm_linux_web_app",
        resource_name: "webapp",
        action: "created",
        status: "success",
        details: "Linux web app 'app-contoso-dev' deployed with Node.js 20 LTS runtime and always-on enabled",
      },
      {
        resource_type: "azurerm_storage_account",
        resource_name: "sa",
        action: "updated",
        status: "success",
        details: "Upgraded min_tls_version from TLS1_0 to TLS1_2 and enforced HTTPS-only traffic",
      },
      {
        resource_type: "azurerm_key_vault",
        resource_name: "kv",
        action: "updated",
        status: "success",
        details: "Enabled purge protection and configured soft delete with 90-day retention period",
      },
    ],
    recommendations: [
      "Configure deployment slots on the web app for blue-green deployments",
      "Enable diagnostic logging on the App Service for application insights",
      "Review key vault access policies and consider migrating to RBAC-based access",
    ],
  };
}

function createApplyDestroyReport(): TerraformReport {
  return {
    status: "Success",
    apply_summary: {
      total_resources: 4,
      created: 0,
      updated: 0,
      destroyed: 4,
      failed: 0,
    },
    execution_summary:
      "All 4 resources in the staging environment were destroyed successfully. Total execution time: 2 minutes 42 seconds. No resources remain in rg-contoso-staging.",
    resource_changes: [
      {
        resource_type: "azurerm_container_group",
        resource_name: "staging_api",
        action: "destroyed",
        status: "success",
        details: "Container group 'ci-staging-api' and all running containers terminated after 30s",
      },
      {
        resource_type: "azurerm_cosmosdb_account",
        resource_name: "staging_db",
        action: "destroyed",
        status: "success",
        details: "Cosmos DB account 'cosmos-staging-001' deleted including all databases and stored data",
      },
      {
        resource_type: "azurerm_redis_cache",
        resource_name: "staging_cache",
        action: "destroyed",
        status: "success",
        details: "Redis cache 'redis-staging-001' (Standard C1) deprovisioned and all cached data purged",
      },
      {
        resource_type: "azurerm_resource_group",
        resource_name: "staging",
        action: "destroyed",
        status: "success",
        details: "Resource group 'rg-contoso-staging' deleted with all remaining child resources after 1m15s",
      },
    ],
    recommendations: [
      "Verify DNS records pointing to staging resources have been updated or removed",
      "Check CI/CD pipelines that reference the staging environment and disable or redirect them",
      "Confirm backup retention policies — Cosmos DB data is unrecoverable after deletion",
    ],
  };
}

function createApplyMixedReport(): TerraformReport {
  return {
    status: "Partial",
    apply_summary: {
      total_resources: 5,
      created: 2,
      updated: 1,
      destroyed: 1,
      failed: 1,
    },
    execution_summary:
      "4 of 5 operations completed successfully. The private endpoint creation failed due to subnet IP address exhaustion. Manual intervention required to resolve the networking issue before retrying.",
    resource_changes: [
      {
        resource_type: "azurerm_postgresql_flexible_server",
        resource_name: "db",
        action: "created",
        status: "success",
        details: "PostgreSQL 16 server 'psql-contoso-pro' provisioned with GP_Standard_D4s_v3 SKU, 128 GB storage, geo-redundant backup",
      },
      {
        resource_type: "azurerm_postgresql_flexible_server_database",
        resource_name: "app_db",
        action: "created",
        status: "success",
        details: "Database 'contoso_pro' created with UTF-8 encoding and en_US.utf8 collation",
      },
      {
        resource_type: "azurerm_storage_account",
        resource_name: "sa",
        action: "updated",
        status: "success",
        details: "Replication upgraded from LRS to ZRS for zone-redundant storage in westeurope",
      },
      {
        resource_type: "azurerm_virtual_machine",
        resource_name: "legacy_worker",
        action: "destroyed",
        status: "success",
        details: "Legacy worker VM 'vm-worker-pro' (Standard_B2s) decommissioned after workload migration to ACI",
      },
      {
        resource_type: "azurerm_private_endpoint",
        resource_name: "db_pe",
        action: "created",
        status: "failed",
        details: "Private endpoint 'pe-psql-contoso-pro' creation timed out after 60 seconds",
        error_message:
          "Error: creating Private Endpoint (Subscription: \"a1b2c3d4\" / Resource Group: \"rg-contoso-pro\" / Name: \"pe-psql-contoso-pro\"): polling after creation: context deadline exceeded. The subnet 'snet-endpoints' may not have enough available IP addresses.",
      },
    ],
    recommendations: [
      "Check available IP addresses in subnet 'snet-endpoints' — expand the CIDR range or clean up unused private endpoints",
      "Retry the private endpoint creation after resolving the subnet capacity issue: terraform apply -target=azurerm_private_endpoint.db_pe",
      "The PostgreSQL server is currently accessible via public endpoint — restrict access once the private endpoint is established",
      "Verify application connection strings have been updated to point to the new PostgreSQL server",
    ],
  };
}

function createGeneratePartialReport(): TerraformReport {
  return {
    status: "Partial",
    summary: {
      create: 2,
      update: 0,
      delete: 0,
      recreate: 0,
    },
    detailed_changes: [
      {
        action: "create",
        name: "Resource Group & Storage Account",
        summary: "Creates a resource group and storage account in West Europe. Both resources passed validation.",
        notes: "2 of 3 planned resources validated successfully.",
        details:
          '# azurerm_resource_group.rg will be created\n+ resource "azurerm_resource_group" "rg" {\n    + id       = (known after apply)\n    + location = "westeurope"\n    + name     = "rg-contoso-dev"\n  }\n\n# azurerm_storage_account.sa will be created\n+ resource "azurerm_storage_account" "sa" {\n    + id                        = (known after apply)\n    + location                  = "westeurope"\n    + name                      = "stcontosodev001"\n    + account_replication_type  = "LRS"\n    + account_tier              = "Standard"\n  }',
      },
      {
        action: "create",
        name: "Azure OpenAI Service (FAILED)",
        summary: "The Azure OpenAI Cognitive Services account failed validation. The SKU 'S0' is not available in the 'swedencentral' region for kind 'OpenAI'. You may need to request Azure OpenAI access or select a supported region.",
        notes: "Resource failed validation — not included in the plan.",
        details:
          '# azurerm_cognitive_account.openai will fail validation\n\nError: creating Cognitive Services Account:\n  the SKU "S0" is not available in region "swedencentral" for kind "OpenAI".\n  Available SKUs: none.\n  Request Azure OpenAI access at https://aka.ms/oai/access.',
      },
    ],
    potential_impact: {
      banner: {
        level: "medium",
        title: "Partial Success: 1 Resource Failed Validation",
        description: "2 of 3 resources passed validation. The Azure OpenAI service could not be provisioned due to region/SKU restrictions. The remaining resources can be deployed safely.",
      },
      summary:
        "This plan will create a resource group and storage account in West Europe. The Azure OpenAI Cognitive Services account was excluded because the requested SKU is not available in the swedencentral region. You may need to request Azure OpenAI access through Microsoft's application process or select a different region where the service is available.",
      bullet_points: [
        {
          title: "Resource Group & Storage",
          description: "Both resources passed validation and can be deployed immediately. The storage account uses Standard LRS with TLS 1.2.",
        },
        {
          title: "Azure OpenAI (Blocked)",
          description: "The S0 SKU is not available in swedencentral. Azure OpenAI requires an approved access application. Apply at https://aka.ms/oai/access.",
        },
      ],
    },
    estimated_costs: {
      currency: "USD",
      total_fixed_monthly_cost: 21.0,
      introduction_paragraph:
        "Cost estimate covers only the 2 resources that passed validation. The Azure OpenAI service cost would depend on the model and usage tier once access is approved.",
      breakdown: [
        {
          resource_type: "Azure Storage Account (azurerm_storage_account)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 21.0,
          notes: "Standard LRS storage based on estimated 100 GB stored data.",
        },
        {
          resource_type: "Azure Resource Group (azurerm_resource_group)",
          pricing_model: "free",
          fixed_monthly_cost: 0.0,
          notes: "Resource groups are free organizational constructs.",
        },
      ],
    },
  };
}

function createGenerateMultiReport(): TerraformReport {
  return {
    status: "Succeeded",
    summary: {
      create: 20,
      update: 0,
      delete: 0,
      recreate: 0,
    },
    detailed_changes: [
      {
        action: "create",
        name: "Resource Group",
        summary: "Creates the production resource group in West Europe as the container for all Contoso platform resources.",
        notes: "Foundation resource — all other resources depend on this.",
        details:
          '# azurerm_resource_group.rg will be created\n+ resource "azurerm_resource_group" "rg" {\n    + id       = (known after apply)\n    + location = "westeurope"\n    + name     = "rg-contoso-pro"\n  }',
      },
      {
        action: "create",
        name: "Virtual Network & Subnets",
        summary: "Creates a /16 VNet with 3 subnets: app (/24) with service endpoints, database (/24) with PostgreSQL delegation, and private endpoints (/24).",
        notes: "5 resources: 1 VNet + 3 subnets + implicit route tables.",
        details:
          '# azurerm_virtual_network.vnet will be created\n+ resource "azurerm_virtual_network" "vnet" {\n    + address_space = ["10.0.0.0/16"]\n    + name          = "vnet-contoso-pro"\n  }\n\n# azurerm_subnet.app will be created (10.0.1.0/24)\n# azurerm_subnet.db will be created (10.0.2.0/24, delegated to PostgreSQL)\n# azurerm_subnet.pe will be created (10.0.3.0/24)',
      },
      {
        action: "create",
        name: "Network Security Groups",
        summary: "Creates 2 NSGs with least-privilege rules. The DB NSG allows PostgreSQL (5432) only from the app subnet. Both NSGs are associated with their respective subnets.",
        notes: "4 resources: 2 NSGs + 2 subnet associations.",
        details:
          '# azurerm_network_security_group.app_nsg will be created\n# azurerm_subnet_network_security_group_association.app will be created\n# azurerm_network_security_group.db_nsg will be created (allows 5432 from 10.0.1.0/24)\n# azurerm_subnet_network_security_group_association.db will be created',
      },
      {
        action: "create",
        name: "Storage Account",
        summary: "Creates a ZRS storage account with TLS 1.2, network rules restricting access to the app subnet only.",
        notes: "Zone-redundant storage for high availability.",
        details:
          '# azurerm_storage_account.sa will be created\n+ resource "azurerm_storage_account" "sa" {\n    + name                     = "stnebpro001"\n    + account_replication_type = "ZRS"\n    + min_tls_version          = "TLS1_2"\n    + network_rules { default_action = "Deny" }\n  }',
      },
      {
        action: "create",
        name: "PostgreSQL Flexible Server & Database",
        summary: "Creates a PostgreSQL 16 flexible server (GP_Standard_D4s_v3) in the delegated subnet with private DNS, geo-redundant backup, and a dedicated application database.",
        notes: "4 resources: server + database + private DNS zone + VNet link.",
        details:
          '# azurerm_postgresql_flexible_server.psql will be created\n+ resource "azurerm_postgresql_flexible_server" "psql" {\n    + name                         = "psql-contoso-pro"\n    + version                      = "16"\n    + sku_name                     = "GP_Standard_D4s_v3"\n    + storage_mb                   = 65536\n    + geo_redundant_backup_enabled = true\n    + zone                         = "1"\n  }\n\n# azurerm_postgresql_flexible_server_database.app_db will be created\n# azurerm_private_dns_zone.psql will be created\n# azurerm_private_dns_zone_virtual_network_link.psql will be created',
      },
      {
        action: "create",
        name: "Key Vault & Secrets",
        summary: "Creates a Key Vault with RBAC authorization, purge protection (90-day retention), network ACLs, and stores the database connection string as a secret.",
        notes: "2 resources: vault + 1 secret. Purge protection prevents accidental deletion.",
        details:
          '# azurerm_key_vault.kv will be created\n+ resource "azurerm_key_vault" "kv" {\n    + name                      = "kv-contoso-pro"\n    + purge_protection_enabled  = true\n    + enable_rbac_authorization = true\n    + soft_delete_retention_days = 90\n  }\n\n# azurerm_key_vault_secret.db_connection_string will be created',
      },
      {
        action: "create",
        name: "Monitoring (Log Analytics & App Insights)",
        summary: "Creates a Log Analytics workspace with 90-day retention and an Application Insights instance linked to it for end-to-end observability.",
        notes: "2 resources: workspace + App Insights.",
        details:
          '# azurerm_log_analytics_workspace.law will be created\n+ resource "azurerm_log_analytics_workspace" "law" {\n    + name              = "law-contoso-pro"\n    + sku               = "PerGB2018"\n    + retention_in_days = 90\n  }\n\n# azurerm_application_insights.ai will be created\n+ resource "azurerm_application_insights" "ai" {\n    + name             = "ai-contoso-pro"\n    + application_type = "web"\n  }',
      },
    ],
    potential_impact: {
      banner: {
        level: "medium",
        title: "Production Infrastructure: 20 New Resources",
        description: "This plan creates the complete Contoso production stack from scratch. All resources are new — no existing infrastructure is modified or destroyed. Review network rules and database configuration before applying.",
      },
      summary:
        "This plan provisions the full production infrastructure for the Contoso platform across 7 Terraform files. It includes isolated networking with three purpose-specific subnets, least-privilege NSG rules, a zone-redundant storage account, a geo-redundant PostgreSQL 16 database with private connectivity, a Key Vault with RBAC and purge protection for secrets management, and centralized monitoring via Log Analytics and Application Insights. All resources are tagged consistently and follow Azure naming conventions (CAF). The database connection string is stored as a Key Vault secret rather than in application configuration.",
      bullet_points: [
        {
          title: "Network Isolation",
          description:
            "Three subnets separate application, database, and private endpoint traffic. NSGs enforce least-privilege: only the app subnet can reach PostgreSQL on port 5432. Storage and Key Vault access is restricted to the app subnet via service endpoints and network ACLs.",
        },
        {
          title: "Database",
          description:
            "PostgreSQL 16 on GP_Standard_D4s_v3 with 64 GB storage, zone 1 placement, and geo-redundant backup. Private DNS ensures the database is only reachable within the VNet. The admin password must be provided via the db_admin_password variable.",
        },
        {
          title: "Secrets Management",
          description:
            "Key Vault uses RBAC authorization (no access policies). Purge protection with 90-day retention prevents accidental or malicious secret deletion. The database connection string is stored as a secret automatically.",
        },
        {
          title: "Observability",
          description:
            "Log Analytics workspace with 90-day retention captures platform logs. Application Insights provides request tracing, dependency mapping, and performance metrics for the web application layer.",
        },
      ],
    },
    estimated_costs: {
      currency: "USD",
      total_fixed_monthly_cost: 567.03,
      introduction_paragraph:
        "Cost estimates are based on Azure public pricing for the West Europe region. The largest cost drivers are the PostgreSQL flexible server and the Log Analytics workspace. Actual costs will vary based on storage consumption, query volume, and data ingestion rates.",
      breakdown: [
        {
          resource_type: "PostgreSQL Flexible Server (azurerm_postgresql_flexible_server)",
          pricing_model: "fixed",
          fixed_monthly_cost: 315.0,
          notes: "GP_Standard_D4s_v3 (4 vCPU, 16 GB RAM) with 64 GB storage and geo-redundant backup. Ranges $280–$350; cost scales with storage growth and backup retention. High-availability add-on not included.",
        },
        {
          resource_type: "Log Analytics Workspace (azurerm_log_analytics_workspace)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 140.0,
          notes: "PerGB2018 pricing at ~$2.76/GB ingested. Estimate assumes 40–65 GB/month of log data ($100–$180). 90-day retention is free for the first 31 days; additional retention at ~$0.10/GB/month.",
        },
        {
          resource_type: "Storage Account — ZRS (azurerm_storage_account)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 46.0,
          notes: "Zone-redundant storage based on estimated 200 GB stored data. ZRS is ~1.5x LRS pricing for cross-zone replication. Transaction costs add ~$5/month at moderate usage.",
        },
        {
          resource_type: "Key Vault — Standard (azurerm_key_vault)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 0.03,
          notes: "Standard tier: $0.03 per 10,000 operations. Secret storage is free. Cost is negligible for typical usage patterns.",
        },
        {
          resource_type: "Application Insights (azurerm_application_insights)",
          pricing_model: "usage_based",
          fixed_monthly_cost: 65.0,
          notes: "First 5 GB/month free, then $2.76/GB. Estimate assumes 20–30 GB telemetry/month ($50–$80). Sampling can reduce volume significantly.",
        },
        {
          resource_type: "Networking (VNet, Subnets, NSGs, DNS)",
          pricing_model: "fixed",
          fixed_monthly_cost: 1.0,
          notes: "VNets, subnets, and NSGs are free. Private DNS zone costs $0.50/zone/month. No VPN gateways or peering included.",
        },
        {
          resource_type: "Resource Group (azurerm_resource_group)",
          pricing_model: "free",
          fixed_monthly_cost: 0.0,
          notes: "Resource groups are free organizational constructs in Azure.",
        },
      ],
    },
  };
}

function createDriftFailedReport(): TerraformReport {
  return {
    status: "Failed",
    remediation_summary:
      "Drift detection failed. Terraform could not acquire the state lock — another operation is currently running.",
    remediated_resources: [],
    recommendations: [
      "Wait for the in-progress CI plan operation to complete before retrying drift detection",
      "If the lock is stale, manually release it with 'terraform force-unlock <LOCK_ID>'",
      "Consider configuring state lock timeouts in your backend configuration",
    ],
  };
}

function createDriftPartialReport(): TerraformReport {
  return {
    status: "Partial",
    remediation_summary:
      "2 of 3 drifted resources have been remediated. 1 resource was skipped due to a dependency conflict.",
    remediated_resources: [
      {
        resource_address: "azurerm_storage_account.sa",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "account_tier",
            change_description: "Standard -> Premium (drifted in portal)",
            reason: "Manual change detected in Azure portal",
            details: [
              "Reverted account_tier from Premium back to Standard",
              "Updated Terraform state to match desired config",
            ],
          },
        ],
      },
      {
        resource_address: "azurerm_network_security_group.nsg",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "security_rule[AllowHTTPS].source_address_prefix",
            change_description: '"*" -> "10.0.0.0/8"',
            reason: "NSG rule was relaxed to allow all inbound HTTPS traffic",
            details: [
              "Restored source_address_prefix to 10.0.0.0/8 (internal only)",
            ],
          },
        ],
      },
    ],
    recommendations: [
      "Resolve the private endpoint dependency on Key Vault 'kv-contoso-dev' before retrying remediation",
      "Remove or modify the private endpoint connection, then re-run drift remediation for the key vault",
      "Consider importing the private endpoint into Terraform state if it was created outside of Terraform",
    ],
  };
}

function createPartialDriftReport(): TerraformReport {
  return {
    status: "Succeeded",
    remediation_summary:
      "2 of 2 drifted storage accounts have been remediated. All scanned resources now match the desired Terraform state.",
    remediated_resources: [
      {
        resource_address: "azurerm_storage_account.sa_hot",
        file_path: "environments/dev/storage.tf",
        changes: [
          {
            attribute_modified: "min_tls_version",
            change_description: '"TLS1_0" -> "TLS1_2"',
            reason: "TLS version was downgraded in the Azure portal",
            details: [
              "Restored min_tls_version to TLS1_2 as defined in Terraform",
              "Security compliance: TLS 1.0 is deprecated and vulnerable",
            ],
          },
        ],
      },
      {
        resource_address: "azurerm_storage_account.sa_archive",
        file_path: "environments/dev/storage.tf",
        changes: [
          {
            attribute_modified: "account_replication_type",
            change_description: '"LRS" -> "GRS"',
            reason: "Replication type was downgraded from GRS to LRS outside Terraform",
            details: [
              "Restored account_replication_type to GRS for geo-redundant backup",
              "Archive data now has cross-region redundancy as intended",
            ],
          },
        ],
      },
    ],
  };
}

function createPartialDriftFailedReport(): TerraformReport {
  return {
    status: "Failed",
    remediation_summary:
      "Partial drift detection failed. Terraform could not connect to the provider registry to download required providers.",
    remediated_resources: [],
    recommendations: [
      "Verify network connectivity to registry.terraform.io from the execution environment",
      "Check proxy settings and DNS configuration if running behind a corporate firewall",
      "Consider using a Terraform provider mirror or local filesystem mirror for air-gapped environments",
      "Retry after confirming the Terraform Registry is accessible",
    ],
  };
}

function createPartialDriftPartialReport(): TerraformReport {
  return {
    status: "Partial",
    remediation_summary:
      "2 of 3 drifted networking resources have been remediated. 1 resource was blocked by Azure Policy.",
    remediated_resources: [
      {
        resource_address: "azurerm_virtual_network.vnet",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "address_space",
            change_description: '["10.0.0.0/16", "172.16.0.0/12"] -> ["10.0.0.0/16"]',
            reason: "Additional address space 172.16.0.0/12 was added outside Terraform",
            details: [
              "Removed unauthorized 172.16.0.0/12 address space from VNet",
              "VNet now matches the single 10.0.0.0/16 CIDR defined in Terraform",
            ],
          },
        ],
      },
      {
        resource_address: "azurerm_subnet.app",
        file_path: "environments/dev/network.tf",
        changes: [
          {
            attribute_modified: "address_prefixes",
            change_description: '["10.0.1.0/23"] -> ["10.0.1.0/24"]',
            reason: "Subnet CIDR was expanded from /24 to /23 in the Azure portal",
            details: [
              "Restored subnet to the original /24 CIDR block",
              "The expanded /23 range could have overlapped with other planned subnets",
            ],
          },
        ],
      },
    ],
    recommendations: [
      "The NSG 'nsg-contoso-dev' update was blocked by Azure Policy 'Deny-NSG-Modification'",
      "Contact your Azure administrator to request a policy exemption for the NSG modification",
      "Alternatively, update the Azure Policy to allow changes from the Terraform service principal",
    ],
  };
}

function createImportFailedReport(): TerraformReport {
  return {
    status: "Failed",
    import_summary: {
      total_untracked_resources: 2,
      successfully_imported_count: 1,
      not_imported_count: 1,
      resource_group_name: "rg-legacy-prod",
    },
    resource_details: [
      {
        category: "Compute",
        resource_identifier: "azurerm_resource_group.legacy (rg-legacy-prod)",
        details: "Resource group imported successfully",
      },
      {
        category: "Security",
        resource_identifier: "azurerm_key_vault.legacy_kv (kv-legacy-prod)",
        details: "Import failed — insufficient permissions (missing Microsoft.KeyVault/vaults/read)",
      },
    ],
    recommendations: [
      "Assign the 'Key Vault Reader' role to the Terraform service principal on subscription 'a1b2c3d4'",
      "Alternatively, create a custom role with Microsoft.KeyVault/vaults/read permission",
      "After fixing permissions, retry the import for the Key Vault resource only",
    ],
  };
}

function createImportPartialReport(): TerraformReport {
  return {
    status: "Partial",
    import_summary: {
      total_untracked_resources: 4,
      successfully_imported_count: 3,
      not_imported_count: 1,
      resource_group_name: "rg-legacy-prod",
    },
    resource_details: [
      {
        category: "Compute",
        resource_identifier: "azurerm_resource_group.legacy (rg-legacy-prod)",
        details: "Resource group in northeurope with no tags — imported successfully",
      },
      {
        category: "Storage",
        resource_identifier: "azurerm_storage_account.legacy_sa (stlegacyprod)",
        details: "Standard GRS storage account with TLS 1.2 — imported successfully",
      },
      {
        category: "Security",
        resource_identifier: "azurerm_key_vault.legacy_kv (kv-legacy-prod)",
        details: "Standard tier key vault with purge protection — imported successfully",
      },
      {
        category: "Database",
        resource_identifier: "azurerm_postgresql_flexible_server.legacy_db (psql-legacy-prod)",
        details: "Import failed — server uses pgbouncer connection pooling which requires manual state import with override flags",
      },
    ],
    recommendations: [
      "Import the PostgreSQL server manually: terraform import -var='pgbouncer_enabled=true' azurerm_postgresql_flexible_server.legacy_db <resource_id>",
      "After manual import, run 'terraform plan' to verify the state matches the configuration",
      "Review imported resource tags and apply consistent tagging across all resources",
      "Enable diagnostic settings on the imported key vault for audit logging",
    ],
  };
}

// ─── Public report factory ────────────────────────────────────

export function createMockTerraformReport(
  type: MockContentType,
): TerraformReport {
  switch (type) {
    case "generate_partial":
      return createGeneratePartialReport();
    case "generate_multi":
      return createGenerateMultiReport();
    case "drift":
      return createDriftReport();
    case "drift_failed":
      return createDriftFailedReport();
    case "drift_partial":
      return createDriftPartialReport();
    case "partial_drift":
      return createPartialDriftReport();
    case "partial_drift_failed":
      return createPartialDriftFailedReport();
    case "partial_drift_partial":
      return createPartialDriftPartialReport();
    case "apply":
      return createApplyReport();
    case "apply_create":
      return createApplyCreateReport();
    case "apply_create_update":
      return createApplyCreateUpdateReport();
    case "apply_destroy":
      return createApplyDestroyReport();
    case "apply_mixed":
      return createApplyMixedReport();
    case "import":
      return createImportReport();
    case "import_failed":
      return createImportFailedReport();
    case "import_partial":
      return createImportPartialReport();
    case "destructive":
      return createDestructiveReport();
    case "remove_resource":
      return createRemoveResourceReport();
    default:
      return createGenerateReport();
  }
}


// ─── Scenario assembly ────────────────────────────────────────

/** One generated/modified file, as a single code-change artifact. */
export interface ScenarioFile {
  name: string;
  content: string;
}

/**
 * Everything one round of a scenario produces, already split into the
 * artifacts the backend would have uploaded separately.
 */
export interface Scenario {
  /** `report.type` — the artifact filename prefix on the backend. */
  reportType: ReportType;
  report: TerraformReport;
  plan: string;
  files: ScenarioFile[];
  /** Terraform resource addresses pinned by the plan artifact. */
  targets: string[];
  history: RawHistoryTurn[];
}

/** `<name>…</name>` sections, in emission order. Mirrors the regex the
 *  code viewer uses, so a bundle that renders in the UI splits here. */
function splitBundle(bundle: string): ScenarioFile[] {
  const sections: ScenarioFile[] = [];
  const pattern = /<([\w.-]+)>\n?([\s\S]*?)\n?<\/\1>/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(bundle)) !== null) {
    sections.push({ name: match[1], content: match[2] });
  }
  return sections;
}

/** Resource addresses referenced by a plan, as the plan artifact's
 *  `targets`. Derived from the code so the two never disagree. */
function deriveTargets(files: ScenarioFile[]): string[] {
  const targets = new Set<string>();
  for (const file of files) {
    const pattern = /^\s*(?:\+|-|~|\+\/-)?\s*resource\s+"([\w-]+)"\s+"([\w-]+)"/gm;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(file.content)) !== null) {
      targets.add(`${match[1]}.${match[2]}`);
    }
  }
  return [...targets];
}

/** The report flavour a scenario's artifact is stored under. */
function reportTypeOf(type: MockContentType): ReportType {
  if (type.startsWith("apply")) return "apply";
  if (type.startsWith("import")) return "import";
  if (type.includes("drift")) return "drift";
  return "generate";
}

/**
 * Take a scenario apart into round artifacts. A bundle may carry the
 * plan inline in a `<Terraform_Plan>` section (that is how apply and
 * failure scenarios were captured); otherwise the standalone
 * `PLAN_TEXT` entry is the plan artifact.
 */
export function getScenario(type: MockContentType): Scenario {
  const sections = splitBundle(RESPONSE_MAP[type]);
  const planSection = sections.find((s) => s.name === "Terraform_Plan");
  const files = sections.filter((s) => s.name !== "Terraform_Plan");
  const turn = HISTORY[type];

  return {
    reportType: reportTypeOf(type),
    report: createMockTerraformReport(type),
    plan: planSection?.content ?? PLAN_TEXT[type],
    files,
    targets: deriveTargets(files),
    history: [{ user: turn.user, assistant: turn.assistant }],
  };
}

export { PLAN_TEXT, HISTORY };
