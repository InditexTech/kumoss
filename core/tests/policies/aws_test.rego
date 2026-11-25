# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# The AWS policy against a real `terraform plan` (fixtures/aws) and inline
# changes.
package kumoss.providers.aws_test

import data.kumoss.providers.aws

change(type, address, after) := {"type": type, "address": address, "mode": "managed", "change": {"actions": ["create"], "after": after}}

plan_input(changes) := {"plan": {"resource_changes": changes}}

found(findings) := {[f.rule_id, f.resource] | some f in findings}

test_rules if {
	aws.rules == {"aws_public_ingress", "aws_iam_wildcard_admin", "aws_s3_public_access"}
}

test_real_plan_findings if {
	found(aws.deny) == {
		["aws_public_ingress", "aws_security_group.inline"],
		["aws_public_ingress", "aws_security_group_rule.ssh"],
		["aws_public_ingress", "aws_vpc_security_group_ingress_rule.rdp"],
		["aws_iam_wildcard_admin", "aws_iam_policy.admin"],
		["aws_s3_public_access", "aws_s3_bucket_acl.public"],
		["aws_s3_public_access", "aws_s3_bucket_public_access_block.off"],
	} with input as data.fixtures.aws
}

test_web_ports_and_icmp_may_be_public if {
	count(aws.deny) == 0 with input as plan_input([
		change("aws_vpc_security_group_ingress_rule", "a.https", {"ip_protocol": "tcp", "from_port": 443, "to_port": 443, "cidr_ipv4": "0.0.0.0/0"}),
		change("aws_vpc_security_group_ingress_rule", "a.icmp", {"ip_protocol": "icmp", "from_port": -1, "to_port": -1, "cidr_ipv4": "0.0.0.0/0"}),
		change("aws_security_group_rule", "a.private", {"type": "ingress", "protocol": "tcp", "from_port": 22, "to_port": 22, "cidr_blocks": ["10.0.0.0/8"]}),
	])
}

test_a_port_range_covering_web_ports_is_denied if {
	found(aws.deny) == {["aws_public_ingress", "a.range"]} with input as plan_input([change(
		"aws_security_group_rule", "a.range",
		{"type": "ingress", "protocol": "tcp", "from_port": 80, "to_port": 443, "cidr_blocks": ["0.0.0.0/0"]},
	)])
}

test_unchanged_and_deleted_resources_are_ignored if {
	count(aws.deny) == 0 with input as plan_input([
		{"type": "aws_s3_bucket_acl", "address": "a.old", "mode": "managed", "change": {"actions": ["no-op"], "after": {"acl": "public-read"}}},
		{"type": "aws_s3_bucket_acl", "address": "a.gone", "mode": "managed", "change": {"actions": ["delete"], "after": null}},
	])
}

test_an_inline_role_policy_and_a_single_statement_object_are_read if {
	found(aws.deny) == {["aws_iam_wildcard_admin", "aws_iam_role.r"]} with input as plan_input([change(
		"aws_iam_role", "aws_iam_role.r",
		{"inline_policy": [{"policy": "{\"Statement\":{\"Effect\":\"Allow\",\"Action\":[\"*\"],\"Resource\":\"*\"}}"}]},
	)])
}

test_an_invalid_or_unknown_policy_document_is_not_an_error if {
	count(aws.deny) == 0 with input as plan_input([
		change("aws_iam_policy", "a.bad", {"policy": "not json"}),
		change("aws_iam_policy", "a.unknown", {"policy": null}),
	])
}
