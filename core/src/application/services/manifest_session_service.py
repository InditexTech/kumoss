# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""Where the manifest meets the API: probing before a session, and preparing one.

Before a session, ``ManifestProbeService`` tells the client what the
root module needs, read from the repository's default branch. On a
session's first call, ``SessionInputsService`` saves the user's answers
(or brings the manifest up to date when nothing is asked), commits
``kumoss.yaml`` to the session branch, and hands the run its inputs.
Iteration calls only load the inputs: the manifest is checked once, at
session start.
"""

from src.application.iac_requests import ManifestAnswers
from src.domains.entities.session import SessionContext
from src.domains.exceptions import ManifestInputError
from src.domains.interfaces.git_interface import IGit
from src.domains.interfaces.workspace_interface import IWorkspace
from src.domains.services.manifest_service import ManifestService, platform_variables
from src.domains.value_objects import ManifestResolution, RootModuleRef
from src.shared.constants import TerraformProvider


class ManifestProbeService:
    """What a root module needs before a session can run on it."""

    def __init__(self, workspace: IWorkspace, manifests: ManifestService):
        self.__workspace = workspace
        self.__manifests = manifests

    async def probe(
        self,
        repo_uri: str,
        root_module_path: str | None,
        terraform_provider: TerraformProvider,
    ) -> ManifestResolution:
        """Resolve the module's manifest on the default branch; reads only."""
        await self.__workspace.validate_uri(repo_uri)
        async with self.__workspace.default_branch_clone(repo_uri) as clone:
            directory = self.__workspace.root_module_dir(clone, root_module_path)
            return await self.__manifests.resolve(
                RootModuleRef(repo_uri, root_module_path or "", directory),
                platform_variables(terraform_provider),
            )


class SessionInputsService:
    """Puts a session's root module inputs in place before a run."""

    def __init__(self, manifests: ManifestService, git: IGit):
        self.__manifests = manifests
        self.__git = git

    async def prepare(
        self,
        ctx: SessionContext,
        *,
        first_call: bool,
        answers: ManifestAnswers | None = None,
    ) -> None:
        """Load the inputs into ``ctx``; on a first call, set the manifest up first.

        Raises:
            ManifestInputError: When the first call leaves something the
                module needs unanswered (422), or the answers are invalid.
        """
        module = RootModuleRef(ctx.repo_uri, ctx.root_module_path or "", ctx.call_dir)
        if first_call:
            provided = platform_variables(ctx.terraform_prv)
            if answers is None:
                resolution = await self.__manifests.sync(module, provided)
            else:
                resolution = await self.__manifests.configure(
                    module, answers.answers(), answers.var_files, provided
                )
            if resolution.needs_input:
                raise ManifestInputError(_needs_input_message(resolution), 422)
            # Lands with the session's work; a no-op when nothing changed.
            await self.__git.commit_and_push(ctx.branch_name)
        ctx.set_terraform_inputs(await self.__manifests.inputs(module))


def _needs_input_message(resolution: ManifestResolution) -> str:
    parts: list[str] = []
    if resolution.missing_variables:
        names = ", ".join(v.name for v in resolution.missing_variables)
        parts.append(f"values for {names}")
    if resolution.missing_var_files:
        parts.append(
            "a new var file selection (gone: "
            + ", ".join(resolution.missing_var_files)
            + ")"
        )
    if not parts:
        parts.append("a choice of var files")
    return (
        "The root module needs "
        + " and ".join(parts)
        + ". Probe it with POST /v1/manifest/probe and send the answers in `manifest`."
    )
