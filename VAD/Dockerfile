FROM nvcr.io/nvidia/tritonserver:22.11-py3

LABEL maintainer="NVIDIA"
LABEL repository="tritonserver"
RUN apt-get update  && apt-get -y install \
    python3-dev \
    cmake \
    libsndfile1

COPY requirements.txt .
RUN pip3 install -r requirements.txt

COPY models /models
RUN mkdir -p /logs
ENTRYPOINT tritonserver --model-repository /models --log-file=/logs/tritonserver.log --allow-metrics=true --allow-cpu-metrics=true --log-info=true --log-warning=true --trace-file=/logs/trace.json --trace-rate=1 --trace-level=TIMESTAMPS --trace-log-frequency 10000
