FROM python:3.14-alpine AS build

RUN apk add --no-cache gcc musl-dev libffi-dev libxml2-dev libxslt-dev

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --prefix=/install . gunicorn

FROM python:3.14-alpine

RUN apk add --no-cache libxml2 libxslt && \
    rm -rf /var/cache/apk/*

COPY --from=build /install /usr/local

RUN adduser -D madblog
USER madblog

ENV MADBLOG_CONFIG=/etc/madblog/config.yaml
ENV MADBLOG_CONTENT_DIR=/data

VOLUME /data
VOLUME /etc/madblog/config.yaml

EXPOSE 8000

ENTRYPOINT ["gunicorn", "-w", "8", "-b", "0.0.0.0:8000"]
CMD ["madblog.uwsgi", "/data"]
