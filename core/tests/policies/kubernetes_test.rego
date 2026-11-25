# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The Kubernetes policy against a real `terraform plan` (fixtures/kubernetes)
# and inline changes.
package kumoss.providers.kubernetes_test

import data.kumoss.providers.kubernetes

change(type, address, after) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": after}}

plan_input(changes) := {"plan": {"resource_changes": changes}}

found(findings) := {[f.rule_id, f.resource] | some f in findings}

pod(container, volumes) := {"spec": [{"template": [{"spec": [{"container": [container], "volume": volumes}]}]}]}

test_rules if {
	kubernetes.rules == {"k8s_privilege_escalation", "k8s_runtime_socket", "k8s_cluster_admin_sa"}
}

test_real_plan_findings if {
	found(kubernetes.deny) == {
		["k8s_privilege_escalation", "kubernetes_deployment_v1.app"],
		["k8s_runtime_socket", "kubernetes_deployment_v1.app"],
		["k8s_cluster_admin_sa", "kubernetes_cluster_role_binding_v1.admin"],
	} with input as data.fixtures.kubernetes
}

test_a_cron_job_nested_container_is_found if {
	found(kubernetes.deny) == {["k8s_privilege_escalation", "a.cron"]} with input as plan_input([change(
		"kubernetes_cron_job_v1", "a.cron",
		{"spec": [{"job_template": [pod({"security_context": [{"allow_privilege_escalation": true}]}, [])]}]},
	)])
}

test_safe_pods_pass if {
	count(kubernetes.deny) == 0 with input as plan_input([change(
		"kubernetes_daemon_set_v1", "a.logs",
		pod({"security_context": [{"allow_privilege_escalation": false}]}, [{"host_path": [{"path": "/var/log"}]}]),
	)])
}

test_runtime_paths_are_normalized if {
	found(kubernetes.deny) == {["k8s_runtime_socket", "a.run"]} with input as plan_input([change(
		"kubernetes_pod_v1", "a.run",
		pod({}, [{"host_path": [{"path": "/run/containerd/"}]}]),
	)])
}

test_cluster_admin_for_users_and_other_roles_pass if {
	count(kubernetes.deny) == 0 with input as plan_input([
		change("kubernetes_cluster_role_binding_v1", "a.user", {"role_ref": [{"kind": "ClusterRole", "name": "cluster-admin"}], "subject": [{"kind": "Group", "name": "admins"}]}),
		change("kubernetes_role_binding_v1", "a.view", {"role_ref": [{"kind": "ClusterRole", "name": "view"}], "subject": [{"kind": "ServiceAccount", "name": "app"}]}),
	])
}
