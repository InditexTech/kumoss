# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The Azure policy against plan changes shaped by the azurerm 4.x schema.
package kumoss.providers.azurerm_test

import data.kumoss.providers.azurerm

change(type, address, after) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": after}}

plan_input(changes) := {"plan": {"resource_changes": changes}}

found(findings) := {[f.rule_id, f.resource] | some f in findings}

nsg_rule(extra) := object.union(
	{
		"direction": "Inbound", "access": "Allow", "protocol": "Tcp",
		"source_address_prefix": null, "source_address_prefixes": [],
		"destination_port_range": null, "destination_port_ranges": [],
	},
	extra,
)

test_rules if {
	azurerm.rules == {"azurerm_public_inbound", "azurerm_subscription_owner", "azurerm_host_command"}
}

test_internet_ssh_and_any_inline_rule_are_denied if {
	found(azurerm.deny) == {
		["azurerm_public_inbound", "azurerm_network_security_rule.ssh"],
		["azurerm_public_inbound", "azurerm_network_security_group.inline"],
	} with input as plan_input([
		change("azurerm_network_security_rule", "azurerm_network_security_rule.ssh", nsg_rule({"source_address_prefix": "Internet", "destination_port_range": "22"})),
		change("azurerm_network_security_group", "azurerm_network_security_group.inline", {"security_rule": [nsg_rule({"protocol": "*", "source_address_prefix": "*", "destination_port_range": "*"})]}),
	])
}

test_web_ports_private_sources_outbound_and_deny_rules_pass if {
	count(azurerm.deny) == 0 with input as plan_input([
		change("azurerm_network_security_rule", "a.web", nsg_rule({"source_address_prefixes": ["0.0.0.0/0"], "destination_port_ranges": ["80", "443"]})),
		change("azurerm_network_security_rule", "a.private", nsg_rule({"source_address_prefix": "10.0.0.0/8", "destination_port_range": "22"})),
		change("azurerm_network_security_rule", "a.out", nsg_rule({"direction": "Outbound", "source_address_prefix": "*", "destination_port_range": "*"})),
		change("azurerm_network_security_rule", "a.block", nsg_rule({"access": "Deny", "source_address_prefix": "*", "destination_port_range": "*"})),
		change("azurerm_network_security_rule", "a.icmp", nsg_rule({"protocol": "Icmp", "source_address_prefix": "*", "destination_port_range": "*"})),
	])
}

test_owner_or_contributor_at_broad_scope_is_denied if {
	found(azurerm.deny) == {
		["azurerm_subscription_owner", "a.sub"],
		["azurerm_subscription_owner", "a.mg"],
	} with input as plan_input([
		change("azurerm_role_assignment", "a.sub", {"scope": "/subscriptions/0000", "role_definition_name": "Owner", "role_definition_id": null}),
		change("azurerm_role_assignment", "a.mg", {
			"scope": "/providers/Microsoft.Management/managementGroups/root",
			"role_definition_name": null,
			"role_definition_id": "/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c",
		}),
		change("azurerm_role_assignment", "a.rg", {"scope": "/subscriptions/0000/resourceGroups/rg", "role_definition_name": "Contributor", "role_definition_id": null}),
		change("azurerm_role_assignment", "a.reader", {"scope": "/subscriptions/0000", "role_definition_name": "Reader", "role_definition_id": null}),
	])
}

test_custom_script_and_run_command_are_denied if {
	found(azurerm.deny) == {
		["azurerm_host_command", "a.script"],
		["azurerm_host_command", "a.vmss"],
		["azurerm_host_command", "a.run"],
	} with input as plan_input([
		change("azurerm_virtual_machine_extension", "a.script", {"type": "CustomScript"}),
		change("azurerm_virtual_machine_scale_set_extension", "a.vmss", {"type": "CustomScriptExtension"}),
		change("azurerm_virtual_machine_run_command", "a.run", {}),
		change("azurerm_virtual_machine_extension", "a.monitor", {"type": "AzureMonitorLinuxAgent"}),
	])
}

test_a_reader_at_subscription_scope_with_a_null_role_id_passes if {
	count(azurerm.deny) == 0 with input as plan_input([change(
		"azurerm_role_assignment", "a.reader",
		{"scope": "/subscriptions/0000", "role_definition_name": "Reader", "role_definition_id": null},
	)])
}
