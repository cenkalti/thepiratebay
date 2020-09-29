FROM python:3.8.6-alpine3.12

RUN apk update && apk add --no-cache --virtual .build-deps build-base gcc libxml2 libxml2-dev libxslt libxslt-dev libffi libffi-dev

COPY requirements.txt requirements.txt
RUN pip3 install --no-cache-dir -r ./requirements.txt

WORKDIR /opt/thepiratebay
COPY . .

ENV BASE_URL=https://thepiratebay.org/

ENTRYPOINT ["python", "app.py"]

EXPOSE 5000
