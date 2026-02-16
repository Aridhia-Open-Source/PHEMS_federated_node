FROM helmunittest/helm-unittest:3.19.0-1.0.3

COPY --chown=helmuser:helmgroup k8s/federated-node/ /apps/chart
WORKDIR /apps/chart
RUN mkdir artifacts && \
  helm dependencies update

CMD ["."]
