FROM python:3.12-slim

WORKDIR /app

# Install system tools for the deployer (venv, curl for healthchecks)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/

# Storage + deployment scratch directories
RUN mkdir -p /pipeline_outputs /tmp/arsify_deploy

# Pipeline engine port (8001) + deployed-app port range (9000-9099)
EXPOSE 8001
EXPOSE 9000-9099

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
