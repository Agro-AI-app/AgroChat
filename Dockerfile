FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
WORKDIR /opt/agrochat
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libcap2-bin libmagic1 libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && setcap cap_net_bind_service=+ep "$(readlink -f "$(command -v python)")" \
    && useradd --create-home --uid 10001 agrochat \
    && mkdir /data && chown agrochat:agrochat /data
COPY requirements.txt .
RUN uv pip install --system --no-cache --torch-backend cpu -r requirements.txt
COPY agrochat ./agrochat
USER agrochat
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data AGROCHAT_HOST=0.0.0.0 PORT=80
EXPOSE 80
CMD ["python", "-m", "agrochat"]
