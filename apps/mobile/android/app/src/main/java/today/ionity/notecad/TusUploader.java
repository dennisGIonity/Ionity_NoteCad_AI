// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.util.Base64;

import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** A small tus 1.0.0 client (creation + resume) for the brain's /uploads endpoint. PATCH goes as POST with
 *  X-HTTP-Method-Override, because HttpURLConnection has no PATCH; the brain accepts both. */
final class TusUploader {
    static final int CHUNK = 256 * 1024;

    interface Progress { void on(long sent, long total); }

    static final class Rejected extends IOException {
        final int status;
        Rejected(int status, String msg) { super(msg); this.status = status; }
    }

    static final class Result {
        String uploadUrl;
        String captureId;
    }

    private static HttpURLConnection open(String url, String method, String token) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(10000);
        c.setReadTimeout(30000);
        c.setRequestProperty("Tus-Resumable", "1.0.0");
        if (token != null && !token.isEmpty()) c.setRequestProperty("Authorization", "Bearer " + token);
        return c;
    }

    private static String metadata(Map<String, String> meta) {
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : meta.entrySet()) {
            if (e.getValue() == null) continue;
            if (sb.length() > 0) sb.append(',');
            sb.append(e.getKey()).append(' ')
              .append(Base64.encodeToString(e.getValue().getBytes(StandardCharsets.UTF_8), Base64.NO_WRAP));
        }
        return sb.toString();
    }

    /** Uploads the file, resuming at uploadUrl if one is given. Calls back with the upload URL as soon as it exists. */
    static Result upload(String endpoint, String token, File file, Map<String, String> meta, String uploadUrl,
                         java.util.function.Consumer<String> onUrl, Progress progress) throws IOException {
        long total = file.length();
        long offset = -1;
        Result res = new Result();
        if (uploadUrl != null) {
            HttpURLConnection h = open(uploadUrl, "HEAD", token);
            int s = h.getResponseCode();
            String known = h.getHeaderField("Upload-Offset");
            if (s == 200 && known != null && known.matches("\\d+")) {
                offset = Long.parseLong(known);
                res.captureId = h.getHeaderField("NoteCad-Capture-Id");
            } else if (s == 401) {
                throw new Rejected(s, "The phone token was not accepted: pair again");
            } else {
                uploadUrl = null;  // gone or expired on the brain: start again
            }
            h.disconnect();
        }
        if (uploadUrl == null) {
            HttpURLConnection c = open(endpoint, "POST", token);
            c.setRequestProperty("Upload-Length", Long.toString(total));
            c.setRequestProperty("Upload-Metadata", metadata(meta));
            c.setDoOutput(true);
            c.setFixedLengthStreamingMode(0);
            c.getOutputStream().close();
            int s = c.getResponseCode();
            if (s != 201) {
                c.disconnect();
                // 404 here: the workspace is not on that brain (paired to another farm), so retrying cannot help
                throw new Rejected(s, s == 404 ? "This farm is not on the brain: pair again" : "The brain answered " + s);
            }
            String loc = c.getHeaderField("Location");
            uploadUrl = loc == null ? null : new URL(new URL(endpoint), loc).toString();  // relative or absolute
            c.disconnect();
            if (uploadUrl == null) throw new IOException("The brain did not say where to upload");
            offset = 0;
            onUrl.accept(uploadUrl);
        }
        res.uploadUrl = uploadUrl;
        byte[] buf = new byte[CHUNK];
        try (RandomAccessFile in = new RandomAccessFile(file, "r")) {
            while (offset < total) {
                in.seek(offset);
                int n = in.read(buf, 0, (int) Math.min(CHUNK, total - offset));
                HttpURLConnection c = open(uploadUrl, "POST", token);
                c.setRequestProperty("X-HTTP-Method-Override", "PATCH");
                c.setRequestProperty("Content-Type", "application/offset+octet-stream");
                c.setRequestProperty("Upload-Offset", Long.toString(offset));
                c.setDoOutput(true);
                c.setFixedLengthStreamingMode(n);
                try (OutputStream out = c.getOutputStream()) {
                    out.write(buf, 0, n);
                }
                int s = c.getResponseCode();
                String o = c.getHeaderField("Upload-Offset");
                String cid = c.getHeaderField("NoteCad-Capture-Id");
                c.disconnect();
                if (s == 404 || s == 410) {
                    throw new IOException("The upload expired on the brain");  // next try asks again and starts over
                }
                if ((s == 204 || s == 409) && o != null) {
                    offset = Long.parseLong(o);  // 409: the brain has more (or less) than we thought; continue from there
                    if (cid != null) res.captureId = cid;
                    progress.on(offset, total);
                } else {
                    throw new Rejected(s, "The brain answered " + s);
                }
            }
        }
        return res;
    }
}
