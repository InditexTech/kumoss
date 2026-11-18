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
from src.domains.services.database_service import DatabaseService
from src.domains.services.manifest_service import (
    Authorize,
    ManifestService,
    session_providers,
)
from src.domains.value_objects import ManifestResolution, RootModuleRef


class ManifestProbeService:
    """What a root module needs before a session can run on it."""

    def __init__(self, workspace: IWorkspace, manifests: ManifestService):
        self.__workspace = workspace
        self.__manifests = manifests

    async def probe(
        self, repo_uri: str, root_module_path: str | None
    ) -> ManifestResolution:
        """Resolve the module's manifest on the default branch; reads only."""
        await self.__workspace.validate_uri(repo_uri)
        async with self.__workspace.default_branch_clone(repo_uri) as clone:
            directory = self.__workspace.root_module_dir(clone, root_module_path)
            return await self.__manifests.resolve(
                RootModuleRef(repo_uri, root_module_path or "", directory)
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
        authorize: Authorize | None = None,
    ) -> None:
        """Load the inputs into ``ctx``; on a first call, set the manifest up first.

        On a first call the session's providers and scopes come from the
        manifest: ``authorize`` checks them before anything is saved, and
        they are recorded on the session. Iteration calls keep the ones
        recorded then.

        Raises:
            ManifestInputError: When the first call leaves something the
                module needs unanswered (422), or the answers are invalid.
            Whatever ``authorize`` raises, before anything is saved.
        """
        module = RootModuleRef(ctx.repo_uri, ctx.root_module_path or "", ctx.call_dir)
        if first_call:
            if answers is None:
                resolution = await self.__manifests.sync(module, authorize)
            else:
                resolution = await self.__manifests.configure(
                    module,
                    answers.answers(),
                    answers.var_files,
                    answers.scopes,
                    authorize,
                )
            if resolution.needs_input:
                raise ManifestInputError(_needs_input_message(resolution), 422)
            providers = session_providers(resolution.requirements, resolution.manifest)
            await DatabaseService.set_session_providers(ctx.id, providers)
            ctx.set_providers(providers)
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
    if resolution.missing_scopes:
        parts.append("scopes for " + ", ".join(resolution.missing_scopes))
    if not parts:
        parts.append("a choice of var files")
    return (
        "The root module's Kumoss manifest still needs "
        + " and ".join(parts)
        + ". Answer them in the wizard, or probe the root module with POST "
        + "/v1/manifest/probe and send the answers in `manifest`."
    )
