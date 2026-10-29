// Ionity Business Mind Map (IBMM) - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.security.cert.CertificateException;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;

import javax.net.ssl.X509TrustManager;

/** The phone trusts the farm brain's own certificate only when it is the one from the QR (POPIA review, fix 4). */
@RunWith(RobolectricTestRunner.class)
public class TlsPinTest {
    // a throwaway self-signed certificate ("IBMM test brain"); PIN is the SHA-256 of its DER
    private static final String PEM = "-----BEGIN CERTIFICATE-----\n"
        + "MIIBJjCBzaADAgECAgEBMAoGCCqGSM49BAMCMB0xGzAZBgNVBAMMEk5vdGVDYWQg\n"
        + "dGVzdCBicmFpbjAeFw0yNjAxMDEwMDAwMDBaFw0zNTEyMzAwMDAwMDBaMB0xGzAZ\n"
        + "BgNVBAMMEk5vdGVDYWQgdGVzdCBicmFpbjBZMBMGByqGSM49AgEGCCqGSM49AwEH\n"
        + "A0IABIR5Nb8JX8mQl8o3zk5Rijj2ZGYTCXUquBODRpuHsN7IvdUyyxkP3LYSykLn\n"
        + "682eWF1ywJpg1g7boLQLPqPwsiwwCgYIKoZIzj0EAwIDSAAwRQIhAKssw1yAd+mH\n"
        + "ApRlO7YBiMgOlXPXYGUELS0WG2+Xe+8UAiAIjAF4KtA8Vu8SQ90sC0BRY8rF8mib\n"
        + "Hc5ZvjnJHHSR8w==\n"
        + "-----END CERTIFICATE-----\n";
    private static final String PIN = "292fe2731d4b20560c382a2a839be3da539e5af9fb71654c8dce6155e5b971b4";
    private Context ctx;

    @Before
    public void setUp() {
        ctx = ApplicationProvider.getApplicationContext();
        TlsPin.clear(ctx);
    }

    private static X509Certificate cert() throws Exception {
        return (X509Certificate) CertificateFactory.getInstance("X.509")
            .generateCertificate(new ByteArrayInputStream(PEM.getBytes(StandardCharsets.US_ASCII)));
    }

    @Test
    public void addressesAreHostAndPort() {
        assertEquals("192.168.1.20:9788", TlsPin.hostPort("https://192.168.1.20:9788/api/v1/x"));
        assertEquals("farm.example:443", TlsPin.hostPort("https://Farm.Example/x"));
        assertEquals("localhost:80", TlsPin.hostPort("http://localhost"));
        assertNull(TlsPin.hostPort("not a url"));
    }

    @Test
    public void aPinIsKeptAndComesBackAfterARestart() {
        TlsPin.put(ctx, "https://192.168.1.20:9788", PIN.toUpperCase());
        TlsPin.put(ctx, "https://192.168.1.21:9788", "not-a-fingerprint");  // ignored
        TlsPin.load(ctx);
        assertEquals(PIN, TlsPin.pinFor("https://192.168.1.20:9788/api/v1/workspaces"));
        assertNull(TlsPin.pinFor("https://192.168.1.21:9788/"));
        assertNull(TlsPin.pinFor("https://192.168.1.20:443/"));  // another port is another brain
        TlsPin.clear(ctx);  // a revoked phone forgets the brain
        TlsPin.load(ctx);
        assertNull(TlsPin.pinFor("https://192.168.1.20:9788/"));
    }

    @Test
    public void onlyThePairedCertificateIsTrusted() throws Exception {
        X509Certificate[] chain = {cert()};
        assertEquals(PIN, TlsPin.sha256(chain[0].getEncoded()));
        X509TrustManager ok = TlsPin.trustManager(PIN);
        ok.checkServerTrusted(chain, "ECDHE_ECDSA");  // no exception: the brain from the QR
        X509TrustManager other = TlsPin.trustManager(PIN.replace('2', '3'));
        try {
            other.checkServerTrusted(chain, "ECDHE_ECDSA");
            fail("a different certificate must be refused");
        } catch (CertificateException expected) {
            // a man in the middle, or another PC
        }
        try {
            ok.checkServerTrusted(new X509Certificate[0], "ECDHE_ECDSA");
            fail("no certificate must be refused");
        } catch (CertificateException expected) {
            // nothing to check
        }
    }
}
