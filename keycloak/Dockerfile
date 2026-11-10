FROM maven:3.9.11-eclipse-temurin-21 AS builder
WORKDIR /build
COPY keycloak/provider/pom.xml .
COPY keycloak/provider/src src
RUN --mount=type=cache,target=/root/.m2 mvn -B -ntp package

FROM quay.io/keycloak/keycloak:26.8.2
COPY --from=builder /build/target/greenu-qr-provider-1.0.0.jar /opt/keycloak/providers/
COPY keycloak/import/replatform-realm.json /opt/keycloak/data/import/replatform-realm.json
