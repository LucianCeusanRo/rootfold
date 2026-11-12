FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    ROOTFOLD_DATABASE_URL=sqlite:////data/rootfold.db

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples

RUN pip install --no-cache-dir .

EXPOSE 8000
VOLUME ["/data"]
CMD ["uvicorn", "rootfold.main:app", "--host", "0.0.0.0", "--port", "8000"]
