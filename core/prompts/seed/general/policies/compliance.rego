# Kumoss compliance policy.
#
# Evaluated by OPA on the final plan of every generate round, next to the
# LLM compliance check. Input:
#
#   input.plan     the `terraform show -json` / `tofu show -json` document
#   input.kumoss   {"schema": "kumoss.compliance.input/v1",
#                   "providers": ["azurerm", ...]}
#
# Output, all optional (a missing one counts as empty):
#
#   deny   blocking findings: {"rule_id", "message", "resource"?,
#          "severity"?}, severity "error" (default) or "critical"
#   warn   non-blocking findings: {"rule_id", "message", "resource"?}
#   rules  every rule_id this policy evaluates, so the report lists
#          the rules that passed too
#
# Plans are `-target` plans: a rule sees the session's targets only, not
# the whole workspace.
package kumoss.compliance

rules contains "critical_deletion"

# A resource may only be destroyed as part of a replace (the same address
# destroyed and created again). A standalone delete is always denied, even
# when the user requested it: user intent does not authorize deletions.
# `forget` (a `removed` block with `destroy = false`) leaves the real
# object alone and is not a deletion.
deny contains finding if {
	some change in input.plan.resource_changes
	change.mode == "managed"
	change.change.actions == ["delete"]
	finding := {
		"rule_id": "critical_deletion",
		"severity": "critical",
		"resource": change.address,
		"message": sprintf(
			"%s is destroyed without being recreated; standalone deletions are never allowed, even when requested.",
			[change.address],
		),
	}
}
