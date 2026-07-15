# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from opentelemetry.sdk.trace import TracerProvider, SpanLimits
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.semconv.resource import ResourceAttributes
from opentelemetry.trace import Tracer

from src.shared.config import system_config
from src.shared.constants import TracerProject
from src.shared.logger import logging


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
                SimpleSpanProcessor(
                    span_exporter=OTLPSpanExporter(
                        endpoint=f"{system_config.telemetry.collector_url}v1/traces",
                    )
                )
            )
            self.__providers[provider_name] = tracer_provider


_PROVIDERS: dict[TracerProject, TracerProvider] = ProvidersInitializer().providers


def get_tracer() -> Tracer:
    provider = TracerProject.PRO_TERRAFORM_DAY2
    if system_config.environment == "development":
        provider = TracerProject.DEV_TERRAFORM_DAY2
    elif system_config.environment == "staging":
        provider = TracerProject.PRE_TERRAFORM_DAY2
    return _PROVIDERS[provider].get_tracer(provider.value)
