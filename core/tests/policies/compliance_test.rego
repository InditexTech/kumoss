# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Tests for the seed policy at core/prompts/seed/general/policies. Run with
#   opa test core/prompts/seed/general/policies core/tests/policies
# The fixtures are real `show -json` plans (fixtures/<engine>/data.json,
# loaded as data.fixtures.<engine>) that create, delete, replace, forget
# and leave alone one terraform_data each.
package kumoss.compliance_test

import data.kumoss.compliance

kumoss := {"schema": "kumoss.compliance.input/v1", "providers": ["terraform"]}

change(address, actions) := {
	"address": address,
	"mode": "managed",
	"change": {"actions": actions},
}

plan_input(changes) := {"plan": {"resource_changes": changes}, "kumoss": kumoss}

test_rules_lists_critical_deletion if {
	"critical_deletion" in compliance.rules
}

test_terraform_fixture_denies_only_the_standalone_delete if {
	findings := compliance.deny with input as object.union(data.fixtures.terraform, {"kumoss": kumoss})
	{f.resource | some f in findings} == {"terraform_data.deleted"}
}

test_opentofu_fixture_denies_only_the_standalone_delete if {
	findings := compliance.deny with input as object.union(data.fixtures.opentofu, {"kumoss": kumoss})
	{f.resource | some f in findings} == {"terraform_data.deleted"}
}

test_deletion_finding_shape if {
	findings := compliance.deny with input as plan_input([change("aws_s3_bucket.logs", ["delete"])])
	findings == {{
		"rule_id": "critical_deletion",
		"severity": "critical",
		"resource": "aws_s3_bucket.logs",
		"message": "aws_s3_bucket.logs is destroyed without being recreated; standalone deletions are never allowed, even when requested.",
	}}
}

test_replace_is_allowed_in_both_orders if {
	count(compliance.deny) == 0 with input as plan_input([
		change("a.destroy_first", ["delete", "create"]),
		change("a.create_first", ["create", "delete"]),
	])
}

test_forget_is_not_a_deletion if {
	count(compliance.deny) == 0 with input as plan_input([change("a.forgotten", ["forget"])])
}

test_data_sources_are_ignored if {
	count(compliance.deny) == 0 with input as plan_input([{
		"address": "data.a.b",
		"mode": "data",
		"change": {"actions": ["delete"]},
	}])
}

test_plan_without_resource_changes_is_clean if {
	count(compliance.deny) == 0 with input as {"plan": {}, "kumoss": kumoss}
}

test_every_deletion_is_reported if {
	count(compliance.deny) == 2 with input as plan_input([
		change("a.one", ["delete"]),
		change("a.two", ["delete"]),
		change("a.three", ["update"]),
	])
}
