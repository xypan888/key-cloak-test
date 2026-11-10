package com.greenai.auth;

import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.protocol.oidc.grants.OAuth2GrantType;
import org.keycloak.protocol.oidc.grants.OAuth2GrantTypeFactory;

public final class GreenUGrantFactory implements OAuth2GrantTypeFactory {
    public static final String ID = "urn:greenai:params:oauth:grant-type:qr";
    public OAuth2GrantType create(KeycloakSession session) { return new GreenUGrant(); }
    public String getId() { return ID; }
    public String getShortcut() { return "gq"; }
    public void init(Config.Scope config) {}
    public void postInit(KeycloakSessionFactory factory) {}
    public void close() {}
}
