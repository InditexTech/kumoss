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

rules contains rule if some rule in {
	"critical_deletion",
	"customer_managed_key_removed",
	"command_execution",
	"unprotected_credential_output",
	"provider_version_pin",
}

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

_changed contains rc if {
	some rc in input.plan.resource_changes
	rc.mode == "managed"
	some action in rc.change.actions
	action in {"create", "update"}
}

_empty(value) if value == null

_empty(value) if value in {"", [], {}}

# --- customer_managed_key_removed --------------------------------------------
# A customer-managed encryption key set before the change and gone after it,
# on any provider: the data falls back to provider-managed keys. A key whose
# new value is only known at apply time is not judged.

_key_attributes := {
	"kms_key_id", "kms_key_arn", "kms_master_key_id",
	"kms_key_name", "kms_key_self_link", "default_kms_key_name",
	"customer_managed_key", "disk_encryption_set_id", "key_vault_key_id",
}

deny contains finding if {
	some rc in _changed
	before := rc.change.before
	is_object(before)
	walk(before, [path, value])
	count(path) > 0
	path[count(path) - 1] in _key_attributes
	not _empty(value)
	is_object(rc.change.after)
	_empty(object.get(rc.change.after, path, null))
	not _unknown(rc.change, path)
	finding := {
		"rule_id": "customer_managed_key_removed",
		"resource": rc.address,
		"message": sprintf(
			"%s removes its customer-managed encryption key (%s); keep the key once it is set.",
			[rc.address, concat(".", [sprintf("%v", [p]) | some p in path])],
		),
	}
}

# The value at path, or a block holding it, is only known at apply time.
_unknown(change, _) if object.get(change, "after_unknown", {}) == true

_unknown(change, path) if {
	unknown := object.get(change, "after_unknown", {})
	is_object(unknown)
	some n in numbers.range(1, count(path))
	object.get(unknown, array.slice(path, 0, n), false) == true
}

# --- command_execution -------------------------------------------------------
# Terraform running commands: a null_resource or a provisioner on a resource
# the plan creates or updates, or an external data source anywhere (it runs
# its program on every plan).

# Each resource block of the configuration, with the module path it is in.
_configured contains [_module_path(path), resource] if {
	walk(input.plan.configuration, [path, resource])
	count(path) >= 2
	path[count(path) - 2] == "resources"
	is_object(resource)
}

_module_path(path) := concat(".", [sprintf("module.%s", [path[i + 1]]) | some i, step in path; step == "module_calls"])

_address(module, address) := address if module == ""

else := sprintf("%s.%s", [module, address])

# A resource change's module address without count or for_each keys.
_module_of(rc) := regex.replace(rc.module_address, `\[[^\]]*\]`, "") if is_string(rc.module_address)

else := ""

deny contains finding if {
	some rc in _changed
	rc.type == "null_resource"
	finding := {
		"rule_id": "command_execution",
		"resource": rc.address,
		"message": sprintf("%s is a null_resource; Terraform must not run commands.", [rc.address]),
	}
}

deny contains finding if {
	some rc in _changed
	some [module, resource] in _configured
	resource.mode == "managed"
	resource.type == rc.type
	resource.name == rc.name
	module == _module_of(rc)
	some provisioner in object.get(resource, "provisioners", [])
	finding := {
		"rule_id": "command_execution",
		"resource": rc.address,
		"message": sprintf(
			"%s has a %s provisioner; configure hosts through cloud-init or the provider's user data instead.",
			[rc.address, provisioner.type],
		),
	}
}

deny contains finding if {
	some [module, resource] in _configured
	resource.mode == "data"
	resource.type == "external"
	address := _address(module, resource.address)
	finding := {
		"rule_id": "command_execution",
		"resource": address,
		"message": sprintf("%s runs a program on every plan; use a native data source.", [address]),
	}
}

# --- unprotected_credential_output -------------------------------------------
# A root module output whose name looks like a credential, not marked
# sensitive. A guess on the name, so a warning. The message never carries
# the value: the plan holds it in plain text.

_credential_name := `(?i)(password|passwd|secret|token|private_key|api_key|access_key|credential|connection_string)`

warn contains finding if {
	some name, output in input.plan.configuration.root_module.outputs
	regex.match(_credential_name, name)
	not output.sensitive == true
	some action in input.plan.output_changes[name].actions
	action in {"create", "update"}
	finding := {
		"rule_id": "unprotected_credential_output",
		"message": sprintf("Output %q looks like a credential; mark it sensitive = true.", [name]),
	}
}

# --- provider_version_pin ----------------------------------------------------
# A root module provider without a pessimistic constraint on its major
# (`~> X.0`) or minor (`~> X.Y`) version: none at all, an exact pin, or an
# open range. A warning: an existing pin is never changed as a side effect,
# so a workspace may keep one on purpose. Child modules pin for themselves.

_pinned(constraint) if regex.match(`^~>\s*[0-9]+\.[0-9]+$`, trim_space(constraint))

warn contains finding if {
	some provider in object.get(object.get(input.plan, "configuration", {}), "provider_config", {})
	not provider.module_address
	not startswith(provider.full_name, "terraform.io/builtin/")
	constraint := object.get(provider, "version_constraint", "")
	not _pinned(constraint)
	finding := {
		"rule_id": "provider_version_pin",
		"message": _pin_message(provider.full_name, constraint),
	}
}

_pin_message(name, "") := sprintf("Provider %s has no version constraint; pin its major version with `~> X.0`.", [name])

_pin_message(name, constraint) := sprintf(
	"Provider %s is constrained to %q; pin its major version with `~> X.0` (or `~> X.Y`).",
	[name, constraint],
) if constraint != ""
