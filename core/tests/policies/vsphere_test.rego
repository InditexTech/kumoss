# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The vSphere policy against plan changes shaped by the vsphere 2.x schema.
package kumoss.providers.vsphere_test

import data.kumoss.providers.vsphere

change(type, address) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": {}}}

found(findings) := {[f.rule_id, object.get(f, "resource", null)] | some f in findings}

provider(expressions) := {"vsphere": {"name": "vsphere", "expressions": expressions}}

test_rules if {
	vsphere.rules == {"vsphere_host_management", "vsphere_unverified_ssl", "vsphere_snapshot"}
}

test_host_level_resources_and_snapshots if {
	found(vsphere.deny) == {
		["vsphere_host_management", "a.pg"],
		["vsphere_host_management", "a.license"],
		["vsphere_snapshot", "a.snap"],
	} with input as {"plan": {"resource_changes": [
		change("vsphere_host_port_group", "a.pg"),
		change("vsphere_license", "a.license"),
		change("vsphere_virtual_machine_snapshot", "a.snap"),
		change("vsphere_virtual_machine", "a.vm"),
	]}}
}

test_unverified_ssl_in_the_provider_block if {
	found(vsphere.deny) == {["vsphere_unverified_ssl", null]} with input as {"plan": {
		"resource_changes": [],
		"configuration": {"provider_config": provider({"allow_unverified_ssl": {"constant_value": true}})},
	}}
}

test_verified_or_variable_ssl_passes if {
	count(vsphere.deny) == 0 with input as {"plan": {
		"resource_changes": [],
		"configuration": {"provider_config": object.union(
			provider({"allow_unverified_ssl": {"constant_value": false}}),
			{"module.x:vsphere": {"name": "vsphere", "expressions": {"allow_unverified_ssl": {"references": ["var.lab"]}}}},
		)},
	}}
}
