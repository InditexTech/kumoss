FROM python:3.13-bookworm

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ripgrep \
    && rm -rf /var/lib/apt/lists/*

# config.yaml
COPY config.yaml /etc/nebula/

WORKDIR /usr/src/app

# Python dependencies
RUN pip install --no-cache-dir uv
COPY core/pyproject.toml .
RUN uv pip install --system --prerelease=allow -r pyproject.toml

# Copy application code
COPY core/ .

EXPOSE 8000

CMD ["fastapi", "run", "src/main.py"]
