# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from src.shared.exceptions import ExceptionHandler


class JinjaTemplateNotFound(ExceptionHandler):
    pass


class RemoteTemplateFetcherError(ExceptionHandler):
    """Raised when a remote template could not be fetched"""

    pass


class PipelineStatusError(ExceptionHandler):
    pass


class PipelineArtifactListError(ExceptionHandler):
    pass


class PipelineArtifactDownloadError(ExceptionHandler):
    pass


class PipelineTriggerError(ExceptionHandler):
    pass


class ToolDefinitionContextNotFound(ExceptionHandler):
    """Raised when a tool definition is not found given a Context"""

    pass


class ToolDefinitionNameNotFound(ExceptionHandler):
    """Raised when a tool definition is not found given a Tool name"""

    pass


class InferenceCallThinkingToolError(ExceptionHandler):
    """Raised when an inference is invoked with tools and thinking enabled"""

    pass


class InferenceCallWebSearchTools(ExceptionHandler):
    """Raised when an inference is invoked with tools and web search enabled"""

    pass


class InferenceCallAPIError(ExceptionHandler):
    """Raised when all attemps have been exhausted"""

    pass


class PhoenixPromptFetchError(ExceptionHandler):
    """Raised if a prompt could not be fetched from Phoenix API"""

    pass


class PromptSeedLoadError(ExceptionHandler):
    """Raised when a seed YAML file is malformed or fails schema validation"""

    pass


class PromptSeedPushError(ExceptionHandler):
    """Raised when seeding prompts into Phoenix fails (after connect retries)"""

    pass


class TracerProviderError(ExceptionHandler):
    """Raised if a tracer provider could not be initialized"""

    pass


class ProviderOpenInferenceNotFound(ExceptionHandler):
    """Raised when an OpenInference provider couldn't be found"""

    pass


class TracerRootContextError(ExceptionHandler):
    """Raised when a child Span didn't find parent span context"""

    pass


class RipgrepError(ExceptionHandler):
    """Raised when an error is found when executing the ripgrep command"""

    pass


class ToolInferenceParamsError(ExceptionHandler):
    """Raised when an inference tool call doesn't return the expected structure"""

    pass


class TerraformResourceNotFoundException(ExceptionHandler):
    """Raised when a Terraform resource is not found given an ID"""

    pass


class WebSearchToolNoContent(ExceptionHandler):
    """Raised when a web search doesn't return any content"""

    pass


class CloudLoginError(ExceptionHandler):
    """Raised when an error occurs during cloud login"""

    pass


class CliError(ExceptionHandler):
    """Raised when an error occurs during CLI command execution"""

    pass


class CliTimeoutError(ExceptionHandler):
    """Raised when a CLI command times out"""

    pass


class InvalidRepoURI(ExceptionHandler):
    """Raised when `git ls-remote` rejects the URI."""

    pass
