# Kumoss compliance policy for Google Cloud.
#
# Evaluated with the general policy when the root module declares the
# google provider. Same input and decision contract as
# general/policies/compliance; the package is kumoss.providers.google.
# Only resources the plan creates or updates are checked, and only on
# values known at plan time.
package kumoss.providers.google

rules contains rule if some rule in {
	"google_public_ingress",
	"google_sa_key",
	"google_basic_role_to_sa",
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

# --- google_public_ingress ---------------------------------------------------
# Ingress firewall rules from the internet on anything but TCP 80 and 443.

_world := {"0.0.0.0/0", "::/0"}

# Each allowed protocol of an ingress rule: [address, sources, protocol, ports].
_allows contains [rc.address, _list(after, "source_ranges"), object.get(allow, "protocol", null), _list(allow, "ports")] if {
	some rc in _changed
	rc.type == "google_compute_firewall"
	after := rc.change.after
	object.get(after, "direction", null) != "EGRESS" # INGRESS is the default
	not after.disabled == true
	some allow in _list(after, "allow")
}

_allows contains [rc.address, _list(match, "src_ip_ranges"), object.get(l4, "ip_protocol", null), _list(l4, "ports")] if {
	some rc in _changed
	rc.type in {
		"google_compute_firewall_policy_rule",
		"google_compute_network_firewall_policy_rule",
		"google_compute_region_network_firewall_policy_rule",
	}
	after := rc.change.after
	after.direction == "INGRESS"
	after.action == "allow"
	not after.disabled == true
	some match in _list(after, "match")
	some l4 in _list(match, "layer4_configs")
}

_ports(ports) := "every port" if count(ports) == 0

else := sprintf("ports %s", [concat(", ", [sprintf("%v", [p]) | some p in ports])])

_web_only(protocol, ports) if {
	lower(protocol) in {"tcp", "6"}
	count(ports) > 0 # no ports means every port
	every port in ports {
		port in {"80", "443"}
	}
}

deny contains finding if {
	some [address, sources, protocol, ports] in _allows
	is_string(protocol)
	not lower(protocol) in {"icmp", "1", "ipv6-icmp", "58"}
	some source in sources
	source in _world
	not _web_only(protocol, ports)
	finding := {
		"rule_id": "google_public_ingress",
		"resource": address,
		"message": sprintf(
			"%s allows inbound %s on %s from %s; only TCP 80 and 443 may be open to the internet.",
			[address, protocol, _ports(ports), source],
		),
	}
}

# --- google_sa_key -------------------------------------------------------------
# User-managed service account keys.

deny contains finding if {
	some rc in _changed
	rc.type == "google_service_account_key"
	finding := {
		"rule_id": "google_sa_key",
		"resource": rc.address,
		"message": sprintf(
			"%s creates a user-managed service account key; use workload identity federation or an attached service account.",
			[rc.address],
		),
	}
}

# --- google_basic_role_to_sa -------------------------------------------------
# Basic roles (owner, editor, viewer) granted to a service account.

_members(after) := array.concat([m | m := object.get(after, "member", null); is_string(m)], _array(object.get(after, "members", [])))

deny contains finding if {
	some rc in _changed
	regex.match(`^google_.+_iam_(member|binding)$`, rc.type)
	rc.change.after.role in {"roles/owner", "roles/editor", "roles/viewer"}
	some member in _members(rc.change.after)
	is_string(member)
	startswith(member, "serviceAccount:")
	finding := {
		"rule_id": "google_basic_role_to_sa",
		"resource": rc.address,
		"message": sprintf(
			"%s grants the basic role %s to a service account; grant predefined or custom roles instead.",
			[rc.address, rc.change.after.role],
		),
	}
}
