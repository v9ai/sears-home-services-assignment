# Minimal skeleton image — deployment-deliverables replaces this with a hardened
# multi-stage build (COORDINATION.md §3).
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
