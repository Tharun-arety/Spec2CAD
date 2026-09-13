# Backend image. CadQuery/OCC is a ~160 MB native dependency, so this runs as a
# long-lived container process rather than a serverless function -- see
# DEPLOYMENT.md for the measurements behind that decision.
FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# OCC needs these at runtime even headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglu1-mesa libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY spec2cad/ ./spec2cad/
COPY api/ ./api/
COPY examples/ ./examples/
COPY eval/ ./eval/
COPY scripts/ ./scripts/

# Generate the demo inputs at build time so POST /runs/demo works immediately.
RUN python examples/motor_adapter/generate_inputs.py

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
