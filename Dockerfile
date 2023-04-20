FROM python:3.8-slim

ARG GPT_PROMPTS

ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV PIP_DEFAULT_TIMEOUT=100

ENV GPT_PROMPTS_SRC=${GPT_PROMPTS}
ENV GPT_PROMPTS=/code/prompts.tsv

RUN apt-get update
RUN apt-get install -y python3 python3-pip python-dev build-essential python3-venv

RUN mkdir -p /code
ADD . /code
ADD ${GPT_PROMPTS_SRC} ${GPT_PROMPTS}
WORKDIR /code

RUN pip3 install -r requirements.txt

CMD ["bash"]