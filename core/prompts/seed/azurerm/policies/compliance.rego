# Kumoss compliance policy for Azure (azurerm).
#
# Evaluated with the general policy when the root module declares the
# azurerm provider. Same input and decision contract as
# general/policies/compliance; the package is kumoss.providers.azurerm.
# Only resources the plan creates or updates are checked, and only on
# values known at plan time.
package kumoss.providers.azurerm

rules contains rule if some rule in {
	"azurerm_public_inbound",
	"azurerm_subscription_owner",
	"azurerm_host_command",
}

_changed contains rc if {
	some rc in input.plan.resource_changes
	rc.mode == "managed"
	some action in rc.change.actions
	action in {"create", "update"}
}

_array(x) := x if is_array(x)

else := []

# A list field read from a plan object; a missing key counts as empty.
_list(obj, key) := _array(object.get(obj, key, []))

# lower() of a field that may be null or missing; strict builtin errors
# would otherwise turn a null into a policy that cannot be evaluated.
_lower(x) := lower(x) if is_string(x)

else := ""

# The single and plural forms of an NSG rule field, as one set.
_values(rule, single, plural) := {v |
	some v in array.concat([object.get(rule, single, null)], _array(object.get(rule, plural, [])))
	is_string(v)
	v != ""
}

# --- azurerm_public_inbound --------------------------------------------------
# Inbound NSG rules from the internet on anything but TCP 80 and 443.

_nsg_rules contains [rc.address, rc.change.after] if {
	some rc in _changed
	rc.type == "azurerm_network_security_rule"
}

_nsg_rules contains [rc.address, rule] if {
	some rc in _changed
	rc.type == "azurerm_network_security_group"
	some rule in _list(rc.change.after, "security_rule")
}

_internet(source) if _lower(source) in {"*", "internet", "any", "0.0.0.0", "0.0.0.0/0", "::/0"}

_web_only(rule) if {
	_lower(rule.protocol) == "tcp"
	ports := _values(rule, "destination_port_range", "destination_port_ranges")
	count(ports) > 0
	every port in ports {
		port in {"80", "443"}
	}
}

deny contains finding if {
	some [address, rule] in _nsg_rules
	_lower(rule.direction) == "inbound"
	_lower(rule.access) == "allow"
	is_string(rule.protocol)
	_lower(rule.protocol) != "icmp"
	some source in _values(rule, "source_address_prefix", "source_address_prefixes")
	_internet(source)
	not _web_only(rule)
	finding := {
		"rule_id": "azurerm_public_inbound",
		"resource": address,
		"message": sprintf(
			"%s allows inbound %s traffic from %s on ports %s; only TCP 80 and 443 may be open to the internet.",
			[address, rule.protocol, source, concat(", ", sort(_values(rule, "destination_port_range", "destination_port_ranges")))],
		),
	}
}

# --- azurerm_subscription_owner ----------------------------------------------
# Owner or Contributor assigned at subscription or management group scope.

# Built-in role definition ids of Owner and Contributor.
_privileged_role_ids := {"8e3af657-a8ff-443c-a75c-2fe8c4bcb635", "b24988ac-6180-42a0-ab88-20f7382dd24c"}

_privileged(after) if _lower(object.get(after, "role_definition_name", null)) in {"owner", "contributor"}

_privileged(after) if {
	some id in _privileged_role_ids
	endswith(_lower(object.get(after, "role_definition_id", null)), id)
}

_broad(scope) if regex.match(`(?i)^/subscriptions/[^/]+/?$`, scope)

_broad(scope) if regex.match(`(?i)^/providers/microsoft\.management/managementgroups/[^/]+/?$`, scope)

_broad("/")

deny contains finding if {
	some rc in _changed
	rc.type == "azurerm_role_assignment"
	is_string(rc.change.after.scope)
	_broad(rc.change.after.scope)
	_privileged(rc.change.after)
	finding := {
		"rule_id": "azurerm_subscription_owner",
		"resource": rc.address,
		"message": sprintf(
			"%s assigns Owner or Contributor at subscription or management group scope; assign a narrower role or scope.",
			[rc.address],
		),
	}
}

# --- azurerm_host_command ----------------------------------------------------
# Running commands on a host: the CustomScript extension or a run command.

deny contains finding if {
	some rc in _changed
	rc.type in {"azurerm_virtual_machine_extension", "azurerm_virtual_machine_scale_set_extension"}
	_lower(rc.change.after.type) in {"customscript", "customscriptextension"}
	finding := {
		"rule_id": "azurerm_host_command",
		"resource": rc.address,
		"message": sprintf("%s installs the CustomScript extension; configure guests through custom_data (cloud-init).", [rc.address]),
	}
}

deny contains finding if {
	some rc in _changed
	rc.type == "azurerm_virtual_machine_run_command"
	finding := {
		"rule_id": "azurerm_host_command",
		"resource": rc.address,
		"message": sprintf("%s runs a command on a virtual machine; configure guests through custom_data (cloud-init).", [rc.address]),
	}
}
