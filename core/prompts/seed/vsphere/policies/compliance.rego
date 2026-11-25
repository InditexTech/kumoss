# Kumoss compliance policy for VMware vSphere.
#
# Evaluated with the general policy when the root module declares the
# vsphere provider. Same input and decision contract as
# general/policies/compliance; the package is kumoss.providers.vsphere.
# Only resources the plan creates or updates are checked.
package kumoss.providers.vsphere

rules contains rule if some rule in {
	"vsphere_host_management",
	"vsphere_unverified_ssl",
	"vsphere_snapshot",
}

_changed contains rc if {
	some rc in input.plan.resource_changes
	rc.mode == "managed"
	some action in rc.change.actions
	action in {"create", "update"}
}

# --- vsphere_host_management -------------------------------------------------
# ESXi hosts, their networking and licenses belong to the platform team.

deny contains finding if {
	some rc in _changed
	_host_level(rc.type)
	finding := {
		"rule_id": "vsphere_host_management",
		"resource": rc.address,
		"message": sprintf("%s manages host-level configuration (%s), which belongs to the platform team.", [rc.address, rc.type]),
	}
}

_host_level(type) if startswith(type, "vsphere_host")

_host_level(type) if type in {"vsphere_vnic", "vsphere_license"}

# --- vsphere_unverified_ssl --------------------------------------------------
# A provider block turning TLS verification off; the IaC engine's
# environment decides it.

deny contains finding if {
	some config in input.plan.configuration.provider_config
	config.name == "vsphere"
	config.expressions.allow_unverified_ssl.constant_value == true
	finding := {
		"rule_id": "vsphere_unverified_ssl",
		"message": "A vsphere provider block sets allow_unverified_ssl = true; TLS verification comes from the IaC engine's environment.",
	}
}

# --- vsphere_snapshot --------------------------------------------------------
# Snapshots are an operational tool, not infrastructure, and never a backup.

deny contains finding if {
	some rc in _changed
	rc.type == "vsphere_virtual_machine_snapshot"
	finding := {
		"rule_id": "vsphere_snapshot",
		"resource": rc.address,
		"message": sprintf("%s manages a virtual machine snapshot; snapshots are not managed as code.", [rc.address]),
	}
}
