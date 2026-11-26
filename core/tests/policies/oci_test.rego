# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The OCI policy against plan changes shaped by the oci 7.x schema.
package kumoss.providers.oci_test

import data.kumoss.providers.oci

change(type, address, after) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": after}}

plan_input(changes) := {"plan": {"resource_changes": changes}}

found(findings) := {[f.rule_id, f.resource] | some f in findings}

test_rules if {
	oci.rules == {"oci_public_ingress", "oci_bastion_open", "oci_any_user_no_condition"}
}

test_security_list_rules if {
	found(oci.deny) == {["oci_public_ingress", "a.sl"]} with input as plan_input([change(
		"oci_core_security_list", "a.sl",
		{"ingress_security_rules": [
			{"protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"min": 22, "max": 22}]},
			{"protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"min": 443, "max": 443}]},
			{"protocol": "1", "source": "0.0.0.0/0", "tcp_options": []},
		]},
	)])
}

test_web_and_icmp_security_list_rules_pass if {
	count(oci.deny) == 0 with input as plan_input([change(
		"oci_core_security_list", "a.sl",
		{"ingress_security_rules": [
			{"protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"min": 80, "max": 80}]},
			{"protocol": "1", "source": "0.0.0.0/0", "tcp_options": []},
			{"protocol": "all", "source": "10.0.0.0/16", "tcp_options": []},
		]},
	)])
}

test_nsg_rules if {
	found(oci.deny) == {["oci_public_ingress", "a.all"], ["oci_public_ingress", "a.no_ports"]} with input as plan_input([
		change("oci_core_network_security_group_security_rule", "a.all", {"direction": "INGRESS", "protocol": "all", "source": "::/0", "tcp_options": []}),
		change("oci_core_network_security_group_security_rule", "a.no_ports", {"direction": "INGRESS", "protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"destination_port_range": []}]}),
		change("oci_core_network_security_group_security_rule", "a.https", {"direction": "INGRESS", "protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"destination_port_range": [{"min": 443, "max": 443}]}]}),
		change("oci_core_network_security_group_security_rule", "a.egress", {"direction": "EGRESS", "protocol": "all", "source": null, "tcp_options": []}),
	])
}

test_open_bastion if {
	found(oci.deny) == {["oci_bastion_open", "a.open"]} with input as plan_input([
		change("oci_bastion_bastion", "a.open", {"client_cidr_block_allow_list": ["10.0.0.0/8", "0.0.0.0/0"]}),
		change("oci_bastion_bastion", "a.closed", {"client_cidr_block_allow_list": ["203.0.113.0/24"]}),
	])
}

test_any_user_statements if {
	findings := oci.deny with input as plan_input([change(
		"oci_identity_policy", "a.p",
		{"statements": [
			"Allow group admins to manage buckets in compartment c",
			"Allow any-user to read buckets in tenancy",
			"allow ANY-USER to use keys in tenancy where request.principal.type = 'objectstorage'",
		]},
	)])
	found(findings) == {["oci_any_user_no_condition", "a.p"]}
	[f.message | some f in findings] == ["a.p statement 2 allows any-user without a request.principal condition."]
}

test_the_default_security_list_is_checked if {
	found(oci.deny) == {["oci_public_ingress", "a.default"]} with input as plan_input([change(
		"oci_core_default_security_list", "a.default",
		{"ingress_security_rules": [{"protocol": "6", "source": "0.0.0.0/0", "tcp_options": [{"min": 22, "max": 22}]}]},
	)])
}

test_request_principal_inside_a_string_is_no_condition if {
	found(oci.deny) == {["oci_any_user_no_condition", "a.p"]} with input as plan_input([change(
		"oci_identity_policy", "a.p",
		{"statements": ["Allow any-user to read objects in tenancy where target.bucket.name = 'request.principal'"]},
	)])
}

test_a_request_principal_condition_passes if {
	count(oci.deny) == 0 with input as plan_input([change(
		"oci_identity_policy", "a.p",
		{"statements": ["Allow any-user to use keys in tenancy where request.principal.type = 'objectstorage'"]},
	)])
}
