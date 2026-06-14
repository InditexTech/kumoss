# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

from opentelemetry.sdk.trace import TracerProvider, Tracer, SpanLimits
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from openinference.semconv.resource import ResourceAttributes

from src.shared.config import system_config
from src.infrastructure.exceptions import TracerProviderError
from src.shared.constants import TracerProviderEnum
from src.shared.logger import logging


class ProvidersInitializer:
    def __init__(self):
        self.__providers: dict[TracerProviderEnum, TracerProvider] = {}
        self.__init_providers()
        logging.debug("Tracer providers initialized successfully")

    @property
    def providers(self) -> dict[TracerProviderEnum, TracerProvider]:
        return self.__providers

    def __init_providers(self) -> None:
        for provider_name in TracerProviderEnum:
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


_PROVIDERS: dict[TracerProviderEnum, TracerProvider] = ProvidersInitializer().providers


def get_tracer(tracer_name: TracerProviderEnum) -> Tracer:
    provider = _PROVIDERS.get(tracer_name)
    if not provider:
        raise TracerProviderError(
            message=f"Tracer Provider {tracer_name} not found.",
            error_code=404,
        )
    return provider.get_tracer(tracer_name.value)
