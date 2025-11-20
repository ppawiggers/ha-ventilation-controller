FROM python:3.14

COPY requirements.txt .
RUN pip install -r requirements.txt

# no need to copy files into image, they will be mounted from a Kubernetes configmap
