// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.After;
import org.junit.Before;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.Random;
import java.util.TreeMap;

/** The phone's tus client against a small tus server that behaves like the brain's /uploads (services/brain tus.py).
 *  The server is a plain ServerSocket: unit tests compile against Android's Java library, which has no JDK http server. */
@RunWith(RobolectricTestRunner.class)
public class TusUploaderTest {
    @Rule public TemporaryFolder tmp = new TemporaryFolder();

    /** One upload on the fake brain. */
    static final class Upload {
        long length;
        String metadata;
        ByteArrayOutputStream data = new ByteArrayOutputStream();
    }

    /** One request and the answer to it. */
    static final class Exchange {
        String method;
        String path;
        final Map<String, String> headers = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        byte[] body = new byte[0];
        final Map<String, String> reply = new LinkedHashMap<>();
        int status;
    }

    private ServerSocket server;
    private String base;
    private final Map<String, Upload> uploads = new HashMap<>();
    private final List<String> calls = new ArrayList<>();
    private int createStatus = 201;
    private int headStatus = 0;        // 0: answer normally
    private long headLiesBy = 0;       // HEAD reports more than the brain has (a crash after the offset was saved)

    @Before
    public void start() throws IOException {
        server = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"));
        Thread loop = new Thread(() -> {
            while (!server.isClosed()) {
                try (Socket s = server.accept()) {
                    serve(s);
                } catch (IOException closed) {
                    // the test is over
                }
            }
        });
        loop.setDaemon(true);
        loop.start();
        base = "http://127.0.0.1:" + server.getLocalPort() + "/api/v1/uploads";
    }

    @After
    public void stop() throws IOException {
        server.close();
    }

    private static String line(InputStream in) throws IOException {
        StringBuilder sb = new StringBuilder();
        for (int c; (c = in.read()) != -1 && c != '\n'; ) if (c != '\r') sb.append((char) c);
        return sb.toString();
    }

    private void serve(Socket s) throws IOException {
        InputStream in = s.getInputStream();
        Exchange x = new Exchange();
        String[] first = line(in).split(" ");
        x.method = first[0];
        x.path = first[1];
        for (String h; !(h = line(in)).isEmpty(); ) {
            int i = h.indexOf(':');
            x.headers.put(h.substring(0, i).trim(), h.substring(i + 1).trim());
        }
        int n = Integer.parseInt(x.headers.getOrDefault("Content-Length", "0"));
        x.body = new byte[n];
        for (int got = 0; got < n; ) got += in.read(x.body, got, n - got);
        handle(x);
        StringBuilder out = new StringBuilder("HTTP/1.1 " + x.status + " X\r\n");
        for (Map.Entry<String, String> e : x.reply.entrySet()) out.append(e.getKey()).append(": ").append(e.getValue()).append("\r\n");
        out.append("Content-Length: 0\r\nConnection: close\r\n\r\n");
        OutputStream o = s.getOutputStream();
        o.write(out.toString().getBytes(StandardCharsets.US_ASCII));
        o.flush();
    }

    private void handle(Exchange x) throws IOException {
        String method = x.method;
        String override = x.headers.get("X-HTTP-Method-Override");
        if (override != null) method = override.toUpperCase(Locale.ROOT);
        String path = x.path;
        String id = path.substring(path.lastIndexOf('/') + 1);
        calls.add(method + " " + (path.endsWith("/uploads") ? "create" : "upload"));
        byte[] body = x.body;
        if (!"1.0.0".equals(x.headers.get("Tus-Resumable"))) {
            send(x, 412);
            return;
        }
        if (path.endsWith("/uploads") && method.equals("POST")) {
            if (createStatus != 201) {
                send(x, createStatus);
                return;
            }
            Upload u = new Upload();
            u.length = Long.parseLong(x.headers.get("Upload-Length"));
            u.metadata = x.headers.get("Upload-Metadata");
            String nid = "u" + (uploads.size() + 1);
            uploads.put(nid, u);
            x.reply.put("Location", "/api/v1/uploads/" + nid);  // relative, as the brain sends it
            send(x, 201);
            return;
        }
        Upload u = uploads.get(id);
        if (u == null) {
            send(x, 404);
            return;
        }
        if (method.equals("HEAD")) {
            if (headStatus != 0) {
                send(x, headStatus);
                return;
            }
            x.reply.put("Upload-Offset", Long.toString(u.data.size() + headLiesBy));
            send(x, 200);
            return;
        }
        if (method.equals("PATCH")) {
            long offset = Long.parseLong(x.headers.get("Upload-Offset"));
            if (offset != u.data.size()) {
                x.reply.put("Upload-Offset", Long.toString(u.data.size()));
                send(x, 409);
                return;
            }
            u.data.write(body);
            x.reply.put("Upload-Offset", Long.toString(u.data.size()));
            if (u.data.size() == u.length) x.reply.put("NoteCad-Capture-Id", "cap-" + id);
            send(x, 204);
            return;
        }
        send(x, 405);
    }

    private static void send(Exchange x, int status) {
        x.status = status;
    }

    private File audio(int size) throws IOException {
        byte[] b = new byte[size];
        new Random(size).nextBytes(b);
        File f = tmp.newFile("note-" + size + ".m4a");
        Files.write(f.toPath(), b);
        return f;
    }

    private static Map<String, String> meta() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("filename", "note.m4a");
        m.put("workspace", "showcase");
        m.put("context_node_id", null);  // left out, not sent as "null"
        return m;
    }

    @Test
    public void uploadsInChunksAndReturnsTheCapture() throws Exception {
        File f = audio(TusUploader.CHUNK * 2 + 1234);  // three chunks
        List<String> urls = new ArrayList<>();
        List<Long> sent = new ArrayList<>();
        TusUploader.Result r = TusUploader.upload(base, "tok", f, meta(), null, urls::add, (s, t) -> sent.add(s));
        Upload u = uploads.get("u1");
        assertArrayEquals(Files.readAllBytes(f.toPath()), u.data.toByteArray());
        assertEquals("cap-u1", r.captureId);
        assertEquals(base + "/u1", r.uploadUrl);                  // the relative Location resolved against the endpoint
        assertEquals(List.of(base + "/u1"), urls);                // saved before the first byte goes out
        assertEquals(3, sent.size());
        assertEquals(f.length(), (long) sent.get(2));
        String[] pairs = u.metadata.split(",");
        assertEquals(2, pairs.length);
        assertEquals("filename", pairs[0].split(" ")[0]);
        assertEquals("note.m4a", new String(Base64.getDecoder().decode(pairs[0].split(" ")[1]), StandardCharsets.UTF_8));
    }

    @Test
    public void resumesWhereTheBrainStopped() throws Exception {
        File f = audio(TusUploader.CHUNK + 5000);
        byte[] all = Files.readAllBytes(f.toPath());
        Upload u = new Upload();
        u.length = all.length;
        u.data.write(all, 0, 70000);  // the connection dropped after 70,000 bytes
        uploads.put("u9", u);
        TusUploader.Result r = TusUploader.upload(base, "tok", f, meta(), base + "/u9", url -> fail("no new upload"), (s, t) -> { });
        assertArrayEquals(all, u.data.toByteArray());
        assertEquals("cap-u9", r.captureId);
        assertEquals("HEAD upload", calls.get(0));
        assertTrue(calls.stream().noneMatch(c -> c.endsWith("create")));
    }

    @Test
    public void followsTheBrainsOffsetOnA409() throws Exception {
        File f = audio(TusUploader.CHUNK + 999);
        byte[] all = Files.readAllBytes(f.toPath());
        Upload u = new Upload();
        u.length = all.length;
        u.data.write(all, 0, 4096);
        uploads.put("u5", u);
        headLiesBy = 60000;  // HEAD says 64,096, the brain really has 4,096: the 409 sets it right, no gap in the audio
        TusUploader.upload(base, null, f, meta(), base + "/u5", url -> { }, (s, t) -> { });
        assertArrayEquals(all, u.data.toByteArray());
        assertTrue(calls.contains("PATCH upload"));
    }

    @Test
    public void startsAgainWhenTheUploadExpired() throws Exception {
        File f = audio(2000);
        List<String> urls = new ArrayList<>();
        TusUploader.Result r = TusUploader.upload(base, "tok", f, meta(), base + "/gone", urls::add, (s, t) -> { });
        assertEquals(List.of(base + "/u1"), urls);
        assertNotEquals(base + "/gone", r.uploadUrl);
        assertArrayEquals(Files.readAllBytes(f.toPath()), uploads.get("u1").data.toByteArray());
    }

    @Test
    public void aRefusedTokenAsksToPairAgain() throws Exception {
        File f = audio(2000);
        uploads.put("u3", new Upload());
        headStatus = 401;
        try {
            TusUploader.upload(base, "old", f, meta(), base + "/u3", url -> { }, (s, t) -> { });
            fail("expected Rejected");
        } catch (TusUploader.Rejected e) {
            assertEquals(401, e.status);
            assertTrue(e.getMessage().contains("pair again"));
        }
    }

    @Test
    public void aFarmThatIsNotOnTheBrainIsPermanent() throws Exception {
        createStatus = 404;
        try {
            TusUploader.upload(base, "tok", audio(2000), meta(), null, url -> fail("no upload url"), (s, t) -> { });
            fail("expected Rejected");
        } catch (TusUploader.Rejected e) {
            assertEquals(404, e.status);
            assertTrue(e.getMessage().contains("pair again"));
        }
    }
}
