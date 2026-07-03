FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (build-essential for compiling native extensions if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements_telnyx.txt .
RUN pip install --no-cache-dir -r requirements_telnyx.txt

# Copy application files
COPY telnyx_bridge.py .

# Run Uvicorn listening on port 8080 (Cloud Run default)
EXPOSE 8080
CMD ["uvicorn", "telnyx_bridge:app", "--host", "0.0.0.0", "--port", "8080"]
