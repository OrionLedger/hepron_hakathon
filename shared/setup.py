from setuptools import setup, find_packages

setup(
    name="cds-shared",
    version="1.0.0",
    description="Shared library for CDS City Operating System microservices",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "fastapi>=0.104.0",
        "sqlalchemy>=2.0.0",
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "confluent-kafka>=2.3.0",
        "redis>=5.0.0",
        "structlog>=23.0.0",
        "opentelemetry-sdk>=1.20.0",
        "opentelemetry-api>=1.20.0",
        "opentelemetry-exporter-otlp>=1.20.0",
        "opentelemetry-instrumentation-fastapi>=0.41b0",
        "prometheus-client>=0.18.0",
        "python-jose[cryptography]>=3.3.0",
        "httpx>=0.25.0",
        "starlette>=0.27.0",
    ],
)
