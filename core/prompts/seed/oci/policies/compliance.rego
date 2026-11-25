# Kumoss compliance policy for Oracle Cloud Infrastructure.
#
# Evaluated with the general policy when the root module declares the oci
# provider. Same input and decision contract as general/policies/compliance;
# the package is kumoss.providers.oci. Only resources the plan creates or
# updates are checked, and only on values known at plan time.
package kumoss.providers.oci

rules contains rule if some rule in {
	"oci_public_ingress",
	"oci_bastion_open",
	"oci_any_user_no_condition",
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

_world := {"0.0.0.0/0", "::/0"}

# --- oci_public_ingress ------------------------------------------------------
# Security list (default ones included) or NSG ingress from the internet on
# anything but TCP 80 and 443. ICMP (protocol 1 and 58) is left alone: the default security list
# allows path MTU discovery from anywhere.

# Each ingress rule: [address, protocol, source, destination port ranges].
_ingress contains [rc.address, object.get(rule, "protocol", null), object.get(rule, "source", null), _list(rule, "tcp_options")] if {
	some rc in _changed
	rc.type in {"oci_core_security_list", "oci_core_default_security_list"}
	some rule in _list(rc.change.after, "ingress_security_rules")
}

_ingress contains [rc.address, object.get(after, "protocol", null), object.get(after, "source", null), ranges] if {
	some rc in _changed
	rc.type == "oci_core_network_security_group_security_rule"
	after := rc.change.after
	after.direction == "INGRESS"
	ranges := [r | some opt in _list(after, "tcp_options"); some r in _list(opt, "destination_port_range")]
}

# TCP to exactly one of 80 or 443; no port range means every port.
_web_only(protocol, ranges) if {
	protocol == "6"
	count(ranges) > 0
	every r in ranges {
		r.min == r.max
		r.min in {80, 443}
	}
}

deny contains finding if {
	some [address, protocol, source, ranges] in _ingress
	is_string(protocol)
	not protocol in {"1", "58"}
	source in _world
	not _web_only(protocol, ranges)
	finding := {
		"rule_id": "oci_public_ingress",
		"resource": address,
		"message": sprintf(
			"%s allows inbound protocol %s from %s beyond TCP 80 and 443; only TCP 80 and 443 may be open to the internet.",
			[address, protocol, source],
		),
	}
}

# --- oci_bastion_open --------------------------------------------------------
# A Bastion reachable from the whole internet.

deny contains finding if {
	some rc in _changed
	rc.type == "oci_bastion_bastion"
	some cidr in _list(rc.change.after, "client_cidr_block_allow_list")
	cidr in _world
	finding := {
		"rule_id": "oci_bastion_open",
		"resource": rc.address,
		"message": sprintf("%s admits clients from %s; restrict client_cidr_block_allow_list.", [rc.address, cidr]),
	}
}

# --- oci_any_user_no_condition -----------------------------------------------
# "Allow any-user" statements without a request.principal condition.

deny contains finding if {
	some rc in _changed
	rc.type == "oci_identity_policy"
	some i, statement in _list(rc.change.after, "statements")
	is_string(statement)
	regex.match(`(?i)^\s*allow\s+any-user\b`, statement)
	not _principal_condition(statement)
	finding := {
		"rule_id": "oci_any_user_no_condition",
		"resource": rc.address,
		"message": sprintf(
			"%s statement %d allows any-user without a request.principal condition.",
			[rc.address, i + 1],
		),
	}
}

# A where clause testing a request.principal variable, with quoted
# strings blanked first so a literal such as 'request.principal' is no
# condition.
_principal_condition(statement) if {
	unquoted := regex.replace(statement, `'[^']*'|"[^"]*"`, "''")
	regex.match(`(?i)\bwhere\b.*\brequest\.principal\.[a-z]`, unquoted)
}
