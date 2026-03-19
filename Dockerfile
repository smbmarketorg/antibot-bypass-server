# Use the official Playwright Docker image as base
FROM mcr.microsoft.com/playwright:v1.55.0-noble

# Set working directory
WORKDIR /app

# Install Python and pip (use system Python)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY pyproject.toml pdm.lock ./
RUN pip install --no-cache-dir pdm

# Install project dependencies
RUN pdm install --no-lock --no-editable

# Install playwright system dependencies (fallback installation if PDM didn't include it)
RUN /opt/venv/bin/pip install playwright
RUN /opt/venv/bin/python -m playwright install-deps

# Install Camoufox browser binary during build (avoids 707MB download on first request)
# XDG_CACHE_HOME=/app/cache matches docker-compose env, so camoufox installs to /app/cache/camoufox
ENV XDG_CACHE_HOME="/app/cache"
RUN pdm run python -m camoufox fetch

# Copy application code
COPY app/ ./app/

# Copy seccomp profile for security
COPY seccomp_profile.json ./

# Create necessary directories
RUN mkdir -p /app/logs /app/cache/camoufox
RUN chmod -R 777 /app/cache/camoufox /app/logs

# Stay as root - no USER directive

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application as root
CMD ["pdm", "run", "python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
