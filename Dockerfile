# Same Python version the dependencies were pinned and tested with
FROM python:3.14-slim

# Write logs immediately instead of buffering them, so journald sees them in real time
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies before copying the code: this layer is cached and only
# rebuilt when requirements.txt changes, not on every code edit
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY opsctl/ opsctl/

# Run as an unprivileged user so a compromised process cannot modify the image
RUN useradd --create-home appuser
USER appuser

ENTRYPOINT ["python", "-m", "opsctl"]
