# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from opentelemetry.sdk.trace import TracerProvider, SpanLimits
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.semconv.resource import ResourceAttributes
from opentelemetry.trace import Tracer

from src.shared.config import system_config
from src.shared.constants import OperationType, TracerProject
from src.shared.logger import logging


def _route_tracer_project(operation: OperationType) -> TracerProject:
    match operation:
        case OperationType.GENERATE:
            match system_config.environment:
                case "production":
                    return TracerProject.PRO_TERRAFORM_DAY2
                case "development":
                    return TracerProject.DEV_TERRAFORM_DAY2
                case "staging":
                    return TracerProject.PRE_TERRAFORM_DAY2
        case OperationType.DRIFT:
            match system_config.environment:
                case "production":
                    return TracerProject.PRO_TERRAFORM_DRIFT
                case "development":
                    return TracerProject.DEV_TERRAFORM_DRIFT
                case "staging":
                    return TracerProject.PRE_TERRAFORM_DRIFT
        case OperationType.IMPORT:
            match system_config.environment:
                case "production":
                    return TracerProject.PRO_TERRAFORM_IMPORT
                case "development":
                    return TracerProject.DEV_TERRAFORM_IMPORT
                case "staging":
                    return TracerProject.PRE_TERRAFORM_IMPORT
    raise ValueError(f"Unsupported tracer routing: operation={operation.value!r}, environment={system_config.environment!r}")

class ProvidersInitializer:
    def __init__(self):
        self.__providers: dict[TracerProject, TracerProvider] = {}
        self.__init_providers()
        logging.debug("Tracer providers initialized successfully")

    @property
    def providers(self) -> dict[TracerProject, TracerProvider]:
        return self.__providers

    def __init_providers(self) -> None:
        for provider_name in TracerProject:
            resource = Resource(
                attributes={ResourceAttributes.PROJECT_NAME: provider_name.value}
            )
            tracer_provider = TracerProvider(
                resource=resource,
                span_limits=SpanLimits(
                    max_attributes=system_config.telemetry.otel_attribute_count_limit
                ),
            )
            if system_config.telemetry.otel_console_exporter:
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(ConsoleSpanExporter())
                )
            tracer_provider.add_span_processor(
                BatchSpanProcessor(
                    span_exporter=OTLPSpanExporter(
                        endpoint=f"{system_config.telemetry.collector_url}v1/traces",
                    )
                )
            )
            self.__providers[provider_name] = tracer_provider


_PROVIDERS: dict[TracerProject, TracerProvider] = ProvidersInitializer().providers


def get_tracer(operation: OperationType) -> Tracer:
    project: TracerProject = _route_tracer_project(operation)
    return _PROVIDERS[project].get_tracer(project.value)


def shutdown_tracer_providers() -> None:
    """
    Flushes pending spans and shuts down every tracer provider. Must be called
    on application shutdown: BatchSpanProcessor exports asynchronously and
    unflushed spans would be lost.
    """
    for provider in _PROVIDERS.values():
        provider.shutdown()
