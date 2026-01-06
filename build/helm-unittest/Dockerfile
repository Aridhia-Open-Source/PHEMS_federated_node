FROM helmunittest/helm-unittest:3.18.4-1.0.0

COPY --chown=helmuser:helmgroup k8s/federated-node/ /apps/chart
WORKDIR /apps/chart
RUN mkdir artifacts && \
  helm dependencies update

CMD ["."]
