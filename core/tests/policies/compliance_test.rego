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

update(address, before, after, unknown) := {
	"address": address,
	"mode": "managed",
	"change": {"actions": ["update"], "before": before, "after": after, "after_unknown": unknown},
}

test_rules_lists_the_general_rules if {
	compliance.rules == {"critical_deletion", "customer_managed_key_removed", "command_execution", "unprotected_credential_output"}
}

test_a_removed_customer_managed_key_is_denied if {
	findings := compliance.deny with input as plan_input([
		update("aws_ebs_volume.data", {"kms_key_id": "arn:aws:kms:k"}, {"kms_key_id": null}, {}),
		update("azurerm_storage_account.st", {"customer_managed_key": [{"key_vault_key_id": "k"}]}, {"customer_managed_key": []}, {}),
		update("google_storage_bucket.b", {"encryption": [{"default_kms_key_name": "k"}]}, {"encryption": []}, {}),
	])
	{f.resource | some f in findings; f.rule_id == "customer_managed_key_removed"} == {
		"aws_ebs_volume.data", "azurerm_storage_account.st", "google_storage_bucket.b",
	}
}

test_a_kept_changed_or_unknown_key_is_allowed if {
	count(compliance.deny) == 0 with input as plan_input([
		update("a.kept", {"kms_key_id": "k"}, {"kms_key_id": "k"}, {}),
		update("a.rotated", {"kms_key_id": "k1"}, {"kms_key_id": "k2"}, {}),
		update("a.unknown", {"kms_key_id": "k"}, {"kms_key_id": null}, {"kms_key_id": true}),
		update("a.unknown_block", {"encryption": [{"default_kms_key_name": "k"}]}, {"encryption": []}, {"encryption": true}),
		update("a.unknown_all", {"kms_key_id": "k"}, {"kms_key_id": null}, true),
		update("a.added", {"kms_key_id": null}, {"kms_key_id": "k"}, {}),
		{"address": "a.new", "mode": "managed", "change": {"actions": ["create"], "before": null, "after": {"kms_key_id": null}}},
	])
}

test_the_real_plan_flags_commands_but_not_untouched_legacy if {
	findings := compliance.deny with input as data.fixtures.general
	{f.resource | some f in findings; f.rule_id == "command_execution"} == {
		"null_resource.new",
		"terraform_data.remote",
		"module.m[0].terraform_data.inner",
		"data.external.probe",
	}
}

test_only_unprotected_credential_outputs_warn if {
	findings := compliance.warn with input as data.fixtures.general
	[f.message | some f in findings] == [`Output "db_password" looks like a credential; mark it sensitive = true.`]
}
