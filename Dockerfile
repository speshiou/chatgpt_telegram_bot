FROM python:3.8-slim

ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV PIP_DEFAULT_TIMEOUT=100

RUN apt-get update
RUN apt-get install -y python3 python3-pip build-essential python3-venv
# for voice decoding
RUN apt-get install -y ffmpeg

RUN mkdir -p /code
RUN mkdir -p /code/tmp/voice
ADD . /code
WORKDIR /code

RUN pip3 install -r requirements.txt

CMD ["bash"]