FROM python:3.7.3-alpine3.9

RUN apk update && apk add --no-cache --virtual .build-deps build-base gcc

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r ./requirements.txt

RUN apk del .build-deps

WORKDIR /opt/thepiratebay
COPY . .

ENV BASE_URL=https://thepiratebay.org/

ENTRYPOINT ["python", "./entrypoint.py"]

EXPOSE 5000
