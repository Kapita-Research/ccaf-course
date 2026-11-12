FROM python:3.12-alpine
WORKDIR /app
COPY server.py index.html Claude_Certified_Architect_-_Foundations__Practice_Exam__Study_Mode_.html /app/
ENV CCAF_DATA_DIR=/data PORT=8080 PYTHONUNBUFFERED=1
RUN adduser -D -u 1000 ccaf && mkdir -p /data && chown ccaf /data
USER ccaf
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
CMD ["python", "server.py"]
