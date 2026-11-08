FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OCI_POLYBOT_USE_INSTANCE_METADATA=0
COPY requirements-twap.txt requirements-live-sdk.txt ./
RUN pip install --no-cache-dir -r requirements-twap.txt -r requirements-live-sdk.txt
COPY polymarket_bot ./polymarket_bot
COPY run_bot.py railway_entrypoint.py verify_twap_runtime.py manage_twap.py ./
CMD ["python", "-B", "railway_entrypoint.py"]
