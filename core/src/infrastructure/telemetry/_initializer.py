# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

"""The one OTel tracer provider of the core, exporting to Langfuse.

Langfuse files every trace under the project its API key belongs to, so a
single provider serves every operation and environment: the tracer tells
them apart with Langfuse's own environment field and trace tags.

The provider is the core's own and is never installed as the global OTel
provider, so instrumentation of third-party libraries cannot leak spans
into Langfuse.
"""

import base64

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Tracer

from src.shared.config import system_config
from src.shared.logger import logging

_TRACER_NAME = "kumoss"


def _otlp_headers() -> dict[str, str]:
    telemetry = system_config.telemetry
    credentials = f"{telemetry.public_key}:{telemetry.secret_key}"
    token = base64.b64encode(credentials.encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _build_provider() -> TracerProvider:
    telemetry = system_config.telemetry
    provider = TracerProvider(
        resource=Resource(attributes={SERVICE_NAME: "kumoss-core"}),
        span_limits=SpanLimits(max_attributes=telemetry.otel_attribute_count_limit),
    )
    if telemetry.otel_console_exporter:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    provider.add_span_processor(
        BatchSpanProcessor(
            span_exporter=OTLPSpanExporter(
                endpoint=f"{telemetry.langfuse_url}api/public/otel/v1/traces",
                headers=_otlp_headers(),
            )
        )
    )
    logging.debug("Tracer provider initialized successfully")
    return provider


_PROVIDER: TracerProvider = _build_provider()


def get_tracer() -> Tracer:
    return _PROVIDER.get_tracer(_TRACER_NAME)


def shutdown_tracer_provider() -> None:
    """
    Flushes pending spans and shuts the tracer provider down. Must be called
    on application shutdown: BatchSpanProcessor exports asynchronously and
    unflushed spans would be lost.
    """
    _PROVIDER.shutdown()
