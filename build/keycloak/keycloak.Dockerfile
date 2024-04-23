
FROM alpine:3.19.0

WORKDIR /jars
ENV INFINISPAN_REPO="https://repo1.maven.org/maven2/org/infinispan"
ENV INFINISPAN_VERSION="14.0.27"
RUN wget "${INFINISPAN_REPO}/infinispan-cachestore-jdbc/${INFINISPAN_VERSION}.Final/infinispan-cachestore-jdbc-${INFINISPAN_VERSION}.Final.jar" && \
    wget "${INFINISPAN_REPO}/infinispan-cachestore-jdbc-common-jakarta/${INFINISPAN_VERSION}.Final/infinispan-cachestore-jdbc-common-jakarta-${INFINISPAN_VERSION}.Final.jar"

FROM quay.io/keycloak/keycloak:24.0.2

COPY cache-ispn.xml /opt/keycloak/conf/
COPY --from=0 /jars /opt/keycloak/providers
RUN /opt/keycloak/bin/kc.sh build --cache=ispn --cache-config-file=cache-ispn.xml
