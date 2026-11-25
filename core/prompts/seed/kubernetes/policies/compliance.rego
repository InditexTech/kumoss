# Kumoss compliance policy for Kubernetes.
#
# Evaluated with the general policy when the root module declares the
# kubernetes provider. Same input and decision contract as
# general/policies/compliance; the package is kumoss.providers.kubernetes.
# Only resources the plan creates or updates are checked, and only on
# values known at plan time. Pod specs are searched wherever a resource
# nests them (Deployments, StatefulSets, DaemonSets, Jobs, CronJobs, Pods).
package kumoss.providers.kubernetes

rules contains rule if some rule in {
	"k8s_privilege_escalation",
	"k8s_runtime_socket",
	"k8s_cluster_admin_sa",
}

_changed contains rc if {
	some rc in input.plan.resource_changes
	rc.mode == "managed"
	startswith(rc.type, "kubernetes_")
	some action in rc.change.actions
	action in {"create", "update"}
}

_array(x) := x if is_array(x)

else := []

# A list field read from a plan object; a missing key counts as empty.
_list(obj, key) := _array(object.get(obj, key, []))

# --- k8s_privilege_escalation ------------------------------------------------
# A security context with allow_privilege_escalation = true.

deny contains finding if {
	some rc in _changed
	walk(rc.change.after, [_, value])
	is_object(value)
	value.allow_privilege_escalation == true
	finding := {
		"rule_id": "k8s_privilege_escalation",
		"resource": rc.address,
		"message": sprintf("%s sets allow_privilege_escalation = true on a container.", [rc.address]),
	}
}

# --- k8s_runtime_socket ------------------------------------------------------
# A hostPath volume exposing the container runtime socket.

_runtime_paths := {
	"/",
	"/run", "/var/run",
	"/run/docker.sock", "/var/run/docker.sock",
	"/run/containerd", "/var/run/containerd",
	"/run/containerd/containerd.sock", "/var/run/containerd/containerd.sock",
	"/run/crio", "/var/run/crio",
	"/run/crio/crio.sock", "/var/run/crio/crio.sock",
}

_normalized(path) := "/" if trim_right(path, "/") == ""

else := trim_right(path, "/")

deny contains finding if {
	some rc in _changed
	walk(rc.change.after, [path, value])
	count(path) >= 2
	path[count(path) - 2] == "host_path"
	is_string(value.path)
	host_path := _normalized(value.path)
	host_path in _runtime_paths
	finding := {
		"rule_id": "k8s_runtime_socket",
		"resource": rc.address,
		"message": sprintf("%s mounts the host path %s, which exposes the container runtime socket.", [rc.address, host_path]),
	}
}

# --- k8s_cluster_admin_sa ----------------------------------------------------
# cluster-admin bound to a ServiceAccount.

deny contains finding if {
	some rc in _changed
	rc.type in {
		"kubernetes_cluster_role_binding", "kubernetes_cluster_role_binding_v1",
		"kubernetes_role_binding", "kubernetes_role_binding_v1",
	}
	some ref in _list(rc.change.after, "role_ref")
	ref.kind == "ClusterRole"
	ref.name == "cluster-admin"
	some subject in _list(rc.change.after, "subject")
	subject.kind == "ServiceAccount"
	finding := {
		"rule_id": "k8s_cluster_admin_sa",
		"resource": rc.address,
		"message": sprintf("%s binds cluster-admin to a ServiceAccount; bind a role scoped to what the workload needs.", [rc.address]),
	}
}
