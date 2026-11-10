package com.greenai.auth;

import jakarta.ws.rs.core.Response;
import java.util.Map;
import java.util.Set;
import org.keycloak.events.Errors;
import org.keycloak.events.EventType;
import org.keycloak.models.*;
import org.keycloak.protocol.oidc.OIDCLoginProtocol;
import org.keycloak.protocol.oidc.TokenManager;
import org.keycloak.protocol.oidc.grants.OAuth2GrantTypeBase;
import org.keycloak.representations.AccessTokenResponse;
import org.keycloak.services.CorsErrorResponseException;
import org.keycloak.services.Urls;
import org.keycloak.services.managers.AuthenticationManager;
import org.keycloak.services.managers.AuthenticationSessionManager;
import org.keycloak.services.managers.UserSessionManager;

/** Custom QR grant; only explicitly enabled confidential backend clients can use it. */
public final class GreenUGrant extends OAuth2GrantTypeBase {
    private Map<String, Object> memberDisplay;
    @Override public boolean isConfidentialOnlyGrantType() { return true; }
    @Override public EventType getEventType() { return EventType.LOGIN; }
    @Override public Set<String> getTokenParameterNames() { return Set.of("access_code"); }
    @Override protected boolean useRefreshToken() { return false; }

    @Override public Response process(Context context) {
        setContext(context);
        if (client.isPublicClient() || !"true".equals(client.getAttribute("greenu.qr.enabled"))
                || !"hku".equals(client.getAttribute("greenu.tenant"))) {
            throw fail("unauthorized_client", "QR authentication is not enabled for this client", false);
        }
        // No caller-selected provider, tenant, scopes or member ID is trusted.
        if (formParams.getFirst("scope") != null && !formParams.getFirst("scope").isBlank()) {
            throw fail("invalid_scope", "This QR client uses fixed scopes", false);
        }
        String code = formParams.getFirst("access_code");
        if (code == null || !code.matches("[a-fA-F0-9]{32}")) {
            throw fail("invalid_grant", "Invalid access code", false);
        }
        GreenUClient.Member member;
        try { member = new GreenUClient().verify(code); }
        catch (GreenUClient.Failure e) {
            throw fail(e.invalidCredential ? "invalid_grant" : "temporarily_unavailable",
                e.invalidCredential ? "Membership cannot be validated" : "GreenU verification is unavailable", !e.invalidCredential);
        }
        String username = "hku.greenu." + member.id();
        UserModel user = session.users().getUserByUsername(realm, username);
        if (user == null) {
            user = session.users().addUser(realm, username);
            user.setEnabled(true);
            user.setSingleAttribute("tenant", "hku");
            user.setSingleAttribute("identity_provider", "greenu");
            user.setSingleAttribute("external_member_id", member.id());
        }
        if (!user.isEnabled() || !"hku".equals(user.getFirstAttribute("tenant"))
                || !"greenu".equals(user.getFirstAttribute("identity_provider"))
                || !member.id().equals(user.getFirstAttribute("external_member_id"))) {
            throw fail("invalid_grant", "Account is unavailable", false);
        }
        if (user.getRequiredActionsStream().findAny().isPresent()) {
            throw fail("invalid_grant", "Account requires administrator attention", false);
        }
        event.user(user);
        var root = new AuthenticationSessionManager(session).createAuthenticationSession(realm, false);
        var auth = root.createAuthenticationSession(client);
        auth.setAuthenticatedUser(user);
        auth.setProtocol(OIDCLoginProtocol.LOGIN_PROTOCOL);
        auth.setClientNote(OIDCLoginProtocol.ISSUER,
            Urls.realmIssuer(session.getContext().getUri().getBaseUri(), realm.getName()));
        auth.setClientNote(OIDCLoginProtocol.SCOPE_PARAM, "");
        var userSession = new UserSessionManager(session).createUserSession(root.getId(), realm, user,
            user.getUsername(), clientConnection.getRemoteHost(), "greenu-qr", false, null, null,
            UserSessionModel.SessionPersistenceState.TRANSIENT);
        event.session(userSession);
        AuthenticationManager.setClientScopesInSession(session, auth);
        var clientSession = TokenManager.attachAuthenticationSession(session, userSession, auth);
        updateUserSessionFromClientAuth(userSession);
        memberDisplay = Map.of("maskedInfo", member.maskedInfo(), "balance", member.balance());
        return createTokenResponse(user, userSession, clientSession, "", false, null);
    }
    @Override protected void addCustomTokenResponseClaims(AccessTokenResponse response, ClientSessionContext context) {
        response.setOtherClaims("member", memberDisplay);
    }
    private CorsErrorResponseException fail(String error, String description, boolean unavailable) {
        event.error(unavailable ? Errors.GENERIC_AUTHENTICATION_ERROR : Errors.INVALID_USER_CREDENTIALS);
        return new CorsErrorResponseException(cors, error, description,
            unavailable ? Response.Status.SERVICE_UNAVAILABLE : Response.Status.BAD_REQUEST);
    }
}
