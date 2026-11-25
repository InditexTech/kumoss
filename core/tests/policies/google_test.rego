# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The Google Cloud policy against a real `terraform plan` (fixtures/google)
# and inline changes.
package kumoss.providers.google_test

import data.kumoss.providers.google

change(type, address, after) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": after}}

plan_input(changes) := {"plan": {"resource_changes": changes}}

found(findings) := {[f.rule_id, f.resource] | some f in findings}

test_rules if {
	google.rules == {"google_public_ingress", "google_sa_key", "google_basic_role_to_sa"}
}

test_real_plan_findings if {
	found(google.deny) == {
		["google_public_ingress", "google_compute_firewall.ssh"],
		["google_public_ingress", "google_compute_network_firewall_policy_rule.any"],
		["google_sa_key", "google_service_account_key.key"],
		["google_basic_role_to_sa", "google_project_iam_member.editor"],
		["google_basic_role_to_sa", "google_project_iam_binding.owner"],
	} with input as data.fixtures.google
}

test_egress_disabled_and_portless_rules if {
	found(google.deny) == {["google_public_ingress", "a.all_ports"]} with input as plan_input([
		change("google_compute_firewall", "a.egress", {"direction": "EGRESS", "source_ranges": ["0.0.0.0/0"], "allow": [{"protocol": "all", "ports": []}]}),
		change("google_compute_firewall", "a.off", {"direction": "INGRESS", "disabled": true, "source_ranges": ["0.0.0.0/0"], "allow": [{"protocol": "tcp", "ports": ["22"]}]}),
		change("google_compute_firewall", "a.all_ports", {"direction": null, "source_ranges": ["::/0"], "allow": [{"protocol": "tcp", "ports": []}]}),
		change("google_compute_firewall", "a.iap", {"direction": "INGRESS", "source_ranges": ["35.235.240.0/20"], "allow": [{"protocol": "tcp", "ports": ["22"]}]}),
	])
}

test_predefined_roles_and_human_members_pass if {
	count(google.deny) == 0 with input as plan_input([
		change("google_project_iam_member", "a.viewer_user", {"role": "roles/viewer", "member": "user:a@example.com"}),
		change("google_project_iam_member", "a.predefined", {"role": "roles/storage.objectViewer", "member": "serviceAccount:sa@p.iam.gserviceaccount.com"}),
	])
}
