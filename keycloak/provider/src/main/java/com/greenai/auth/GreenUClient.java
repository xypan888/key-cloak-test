package com.greenai.auth;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

/** GreenU-specific adapter. QR values and upstream responses must never be logged. */
public final class GreenUClient {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final HttpClient HTTP = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build();

    public record Member(String id, String maskedInfo, long balance) {}
    public static final class Failure extends Exception {
        public final boolean invalidCredential;
        public Failure(boolean invalidCredential) { this.invalidCredential = invalidCredential; }
    }
    public Member verify(String code) throws Failure {
        String base = env("GREENU_BASE_URL").replaceAll("/+$", "");
        try {
            URI uri = URI.create(base + "/member/" + code);
            if (!"https".equals(uri.getScheme())) {
                throw new Failure(false);
            }
            var request = HttpRequest.newBuilder(uri)
                .timeout(Duration.ofSeconds(Long.parseLong(System.getenv().getOrDefault("GREENU_TIMEOUT_SECONDS", "10"))))
                .header("api-key", env("GREENU_API_KEY"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(JSON.writeValueAsString(
                    Map.of("merchant", System.getenv().getOrDefault("GREENU_MERCHANT", "GreenAI")))))
                .build();
            var response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() == 404) throw new Failure(true);
            if (response.statusCode() != 200) throw new Failure(false);
            JsonNode body = JSON.readTree(response.body());
            if (!body.path("membership").isBoolean()) throw new Failure(false);
            if (!body.path("membership").booleanValue()) throw new Failure(true);
            String id = body.path("memberID").asText("");
            if (!id.matches("[A-Za-z0-9-]{1,36}") || !body.path("memberBalance").isIntegralNumber()) throw new Failure(false);
            return new Member(id, body.path("memberMaskedInfo").asText(""), body.path("memberBalance").longValue());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new Failure(false);
        } catch (IOException | IllegalArgumentException e) {
            throw new Failure(false);
        }
    }
    private static String env(String name) throws Failure {
        String value = System.getenv(name);
        if (value == null || value.isBlank()) throw new Failure(false);
        return value;
    }
}
