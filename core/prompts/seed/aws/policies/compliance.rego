# Kumoss compliance policy for AWS.
#
# Evaluated with the general policy when the root module declares the aws
# provider. Same input and decision contract as general/policies/compliance;
# the package is kumoss.providers.aws. Only resources the plan creates or
# updates are checked, and only on values known at plan time.
package kumoss.providers.aws

rules contains rule if some rule in {
	"aws_public_ingress",
	"aws_iam_wildcard_admin",
	"aws_s3_public_access",
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

_strings(x) := [x] if is_string(x)

else := _array(x)

# --- aws_public_ingress ------------------------------------------------------
# Security group ingress open to the internet on anything but TCP 80 and 443.

_world := {"0.0.0.0/0", "::/0"}

_ingress contains rule if {
	some rc in _changed
	rc.type == "aws_security_group"
	some block in _list(rc.change.after, "ingress")
	rule := {
		"address": rc.address,
		"protocol": object.get(block, "protocol", null),
		"from": object.get(block, "from_port", null),
		"to": object.get(block, "to_port", null),
		"cidrs": {c | some c in array.concat(_list(block, "cidr_blocks"), _list(block, "ipv6_cidr_blocks"))},
	}
}

_ingress contains rule if {
	some rc in _changed
	rc.type == "aws_security_group_rule"
	rc.change.after.type == "ingress"
	after := rc.change.after
	rule := {
		"address": rc.address,
		"protocol": object.get(after, "protocol", null),
		"from": object.get(after, "from_port", null),
		"to": object.get(after, "to_port", null),
		"cidrs": {c | some c in array.concat(_list(after, "cidr_blocks"), _list(after, "ipv6_cidr_blocks"))},
	}
}

_ingress contains rule if {
	some rc in _changed
	rc.type == "aws_vpc_security_group_ingress_rule"
	after := rc.change.after
	rule := {
		"address": rc.address,
		"protocol": object.get(after, "ip_protocol", null),
		"from": object.get(after, "from_port", null),
		"to": object.get(after, "to_port", null),
		"cidrs": {c | some c in [object.get(after, "cidr_ipv4", null), object.get(after, "cidr_ipv6", null)]; is_string(c)},
	}
}

_web_only(rule) if {
	lower(rule.protocol) in {"tcp", "6"}
	rule.from == rule.to
	rule.from in {80, 443}
}

_traffic(rule) := "all traffic" if rule.protocol == "-1"

else := sprintf("%s ports %v-%v", [rule.protocol, rule.from, rule.to])

_icmp(rule) if lower(rule.protocol) in {"icmp", "1", "icmpv6", "58"}

deny contains finding if {
	some rule in _ingress
	is_string(rule.protocol)
	some cidr in rule.cidrs
	cidr in _world
	not _web_only(rule)
	not _icmp(rule)
	finding := {
		"rule_id": "aws_public_ingress",
		"resource": rule.address,
		"message": sprintf(
			"%s allows inbound %s from %s; only TCP 80 and 443 may be open to the internet.",
			[rule.address, _traffic(rule), cidr],
		),
	}
}

# --- aws_iam_wildcard_admin --------------------------------------------------
# An IAM policy statement allowing every action on every resource.

_policy_documents contains [rc.address, rc.change.after.policy] if {
	some rc in _changed
	rc.type in {"aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy", "aws_iam_group_policy"}
}

_policy_documents contains [rc.address, inline.policy] if {
	some rc in _changed
	rc.type == "aws_iam_role"
	some inline in _list(rc.change.after, "inline_policy")
}

_statements(document) := _array(document.Statement) if is_array(document.Statement)

else := [document.Statement] if is_object(document.Statement)

else := []

deny contains finding if {
	some [address, text] in _policy_documents
	is_string(text)
	json.is_valid(text)
	some statement in _statements(json.unmarshal(text))
	statement.Effect == "Allow"
	"*" in _strings(statement.Action)
	"*" in _strings(statement.Resource)
	finding := {
		"rule_id": "aws_iam_wildcard_admin",
		"resource": address,
		"message": sprintf(
			"%s allows every action (\"*\") on every resource (\"*\"); grant the actions and resources the workload needs.",
			[address],
		),
	}
}

# --- aws_s3_public_access ----------------------------------------------------
# A public bucket ACL, or S3 Block Public Access switched off.

deny contains finding if {
	some rc in _changed
	rc.type in {"aws_s3_bucket_acl", "aws_s3_bucket"}
	acl := object.get(rc.change.after, "acl", null)
	acl in {"public-read", "public-read-write"}
	finding := {
		"rule_id": "aws_s3_public_access",
		"resource": rc.address,
		"message": sprintf("%s sets the public bucket ACL %q.", [rc.address, acl]),
	}
}

_block_public_flags := ["block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"]

deny contains finding if {
	some rc in _changed
	rc.type in {"aws_s3_bucket_public_access_block", "aws_s3_account_public_access_block"}
	off := [flag | some flag in _block_public_flags; object.get(rc.change.after, flag, null) == false]
	count(off) > 0
	finding := {
		"rule_id": "aws_s3_public_access",
		"resource": rc.address,
		"message": sprintf(
			"%s switches off S3 Block Public Access (%s); every flag must stay true.",
			[rc.address, concat(", ", off)],
		),
	}
}
