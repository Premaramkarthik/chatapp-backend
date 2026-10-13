FROM quay.io/keycloak/keycloak:26.0.8@sha256:09a381c715ab0b111835b70f2905955274843a219c6f27efb348e4d9f4086858
COPY deployment/keycloak/themes /opt/keycloak/themes
RUN /opt/keycloak/bin/kc.sh build --db=postgres
