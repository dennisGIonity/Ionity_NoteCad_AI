// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.content.Context;
import android.net.http.SslCertificate;
import android.os.Bundle;

import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/** The brain on the farm network speaks HTTPS with its own certificate, which no authority signs. The pairing QR and
 *  every invite carry its SHA-256 (f=), and this phone trusts exactly that certificate for that address: in the
 *  WebView (MainActivity) and in the background uploads (TusUploader). Any other certificate is refused. A brain with
 *  a certificate from a real authority needs no pin and is checked the normal way. (POPIA review, fix 4.) */
final class TlsPin {
    private static final String KEY = "tls_pins";  // "host:port=sha256;host:port=sha256"
    private static final Map<String, String> PINS = new ConcurrentHashMap<>();

    private TlsPin() {}

    static void load(Context c) {
        PINS.clear();
        String all = OutboxStore.prefs(c).getString(KEY, "");
        for (String kv : all.split(";")) {
            int i = kv.lastIndexOf('=');
            if (i > 0) PINS.put(kv.substring(0, i), kv.substring(i + 1));
        }
    }

    static void put(Context c, String url, String sha256) {
        String hp = hostPort(url);
        if (hp == null || sha256 == null || !sha256.matches("[0-9a-fA-F]{64}")) return;
        PINS.put(hp, sha256.toLowerCase(Locale.ROOT));
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : PINS.entrySet()) {
            if (sb.length() > 0) sb.append(';');
            sb.append(e.getKey()).append('=').append(e.getValue());
        }
        OutboxStore.prefs(c).edit().putString(KEY, sb.toString()).apply();
    }

    static void clear(Context c) {
        PINS.clear();
        OutboxStore.prefs(c).edit().remove(KEY).apply();
    }

    static String hostPort(String url) {
        try {
            URI u = new URI(url);
            if (u.getHost() == null) return null;
            int port = u.getPort() != -1 ? u.getPort() : ("https".equalsIgnoreCase(u.getScheme()) ? 443 : 80);
            return u.getHost().toLowerCase(Locale.ROOT) + ":" + port;
        } catch (Exception e) {
            return null;
        }
    }

    static String pinFor(String url) {
        String hp = hostPort(url);
        return hp == null ? null : PINS.get(hp);
    }

    static String sha256(byte[] der) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(der);
        StringBuilder sb = new StringBuilder();
        for (byte b : d) sb.append(String.format(Locale.ROOT, "%02x", b));
        return sb.toString();
    }

    /** The WebView's question: is this the certificate this phone paired with, for this address? */
    static boolean matches(SslCertificate cert, String url) {
        String pin = pinFor(url);
        if (pin == null || cert == null) return false;
        try {
            Bundle b = SslCertificate.saveState(cert);
            byte[] der = b == null ? null : b.getByteArray("x509-certificate");
            return der != null && pin.equals(sha256(der));
        } catch (Exception e) {
            return false;
        }
    }

    /** An HTTPS connection to a pinned brain trusts that one certificate and nothing else. The host name is not
     *  checked: the pin is the check, and the farm PC's address may change. */
    static void secure(HttpURLConnection c) {
        if (!(c instanceof HttpsURLConnection)) return;
        URL u = c.getURL();
        String pin = pinFor(u.toString());
        if (pin == null) return;
        HttpsURLConnection h = (HttpsURLConnection) c;
        h.setSSLSocketFactory(factory(pin));
        h.setHostnameVerifier((host, session) -> true);
    }

    static SSLSocketFactory factory(final String pin) {
        try {
            SSLContext ctx = SSLContext.getInstance("TLS");
            ctx.init(null, new TrustManager[]{trustManager(pin)}, null);
            return ctx.getSocketFactory();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** Trusts one certificate: the one whose SHA-256 is pin. */
    static X509TrustManager trustManager(final String pin) {
        return new X509TrustManager() {
            @Override public void checkClientTrusted(X509Certificate[] chain, String auth) throws CertificateException {
                throw new CertificateException("no client certificates");
            }
            @Override public void checkServerTrusted(X509Certificate[] chain, String auth) throws CertificateException {
                try {
                    if (chain == null || chain.length == 0 || !pin.equals(sha256(chain[0].getEncoded())))
                        throw new CertificateException("not the brain this phone was paired with");
                } catch (CertificateException e) {
                    throw e;
                } catch (Exception e) {
                    throw new CertificateException(e);
                }
            }
            @Override public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
        };
    }
}
