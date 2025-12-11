"""Main entry point for ventilation control system."""

import os
import logging

from ha import HomeAssistantAPI
from config import load_config
from controller import VentilationController


def setup_logging():
    """Configure logging based on environment.

    Always outputs to stdout. Additionally sends to OpenTelemetry/Dash0
    if OTEL_EXPORTER_OTLP_ENDPOINT is configured.

    Returns:
        LoggerProvider if using OpenTelemetry, None otherwise
    """
    # Always configure stdout logging
    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(
        logging.Formatter(fmt="%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )

    handlers = [stdout_handler]

    # Additionally send to OpenTelemetry/Dash0 if configured
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    logger_provider = None

    if otel_endpoint:
        from opentelemetry import _logs
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk.resources import Resource

        resource = Resource.create(
            {
                "service.name": "ventilation-controller",
                "service.namespace": "homeassistant",
            }
        )

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(endpoint=otel_endpoint, insecure=True)
            )
        )
        _logs.set_logger_provider(logger_provider)

        # Add OTEL handler in addition to stdout
        otel_handler = LoggingHandler(logger_provider=logger_provider)
        handlers.append(otel_handler)

    logging.basicConfig(level=logging.INFO, handlers=handlers)
    return logger_provider


logger = logging.getLogger(__name__)


def main():
    """Run ventilation control cycle."""
    # Setup logging and get logger provider (if using OpenTelemetry)
    logger_provider = setup_logging()

    try:
        # Load configuration
        logger.info("Loading configuration")
        config = load_config()

        # Initialize Home Assistant API
        logger.info("Initializing Home Assistant connection")
        ha = HomeAssistantAPI(
            ha_url=config.global_config.homeassistant_url,
            ha_token=config.global_config.homeassistant_token,
        )

        # Initialize controller
        logger.info("Initializing ventilation controller")
        controller = VentilationController(config, ha)

        # Execute control cycle
        logger.info("Running control cycle")
        controller.run_control_cycle()

        logger.info("Ventilation control cycle completed")
    finally:
        # Ensure logs are flushed before exit
        if logger_provider:
            logger_provider.shutdown()


if __name__ == "__main__":
    main()
