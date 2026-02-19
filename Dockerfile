FROM python:3.14-alpine AS build

RUN apk add --no-cache gcc musl-dev libffi-dev libxml2-dev libxslt-dev

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.14-alpine

RUN apk add --no-cache libxml2 libxslt

COPY --from=build /install /usr/local

RUN adduser -D madblog
USER madblog

VOLUME /data
VOLUME /etc/madblog/config.yaml

EXPOSE 8000

ENTRYPOINT ["madblog", "--config", "/etc/madblog/config.yaml", "--host", "0.0.0.0", "--port", "8000"]
CMD ["/data"]
