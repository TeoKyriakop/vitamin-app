FROM python:3.12-slim
WORKDIR /srv/vitamin-app
COPY app ./app
COPY server ./server
WORKDIR /srv/vitamin-app/server
ENV PORT=8080 VITAPP_STATE=/data/state PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8080
CMD ["python", "-m", "vitapp.server"]
