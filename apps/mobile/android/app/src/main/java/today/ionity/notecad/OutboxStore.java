// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** The native outbox: bubble recordings wait here (audio + a small JSON file) until they are uploaded. */
final class OutboxStore {
    static final String PREFS = "notecad";
    private static final SecureRandom RANDOM = new SecureRandom();

    static File dir(Context c) {
        File d = new File(c.getFilesDir(), "outbox");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    static File audio(Context c, String id) { return new File(dir(c), id + ".m4a"); }

    static File meta(Context c, String id) { return new File(dir(c), id + ".json"); }

    static SharedPreferences prefs(Context c) { return c.getSharedPreferences(PREFS, Context.MODE_PRIVATE); }

    /** Time-ordered UUID (RFC 9562 v7): the capture id is made on the phone, so a retried upload never doubles. */
    static String uuid7() {
        byte[] b = new byte[16];
        RANDOM.nextBytes(b);
        long ms = System.currentTimeMillis();
        for (int i = 0; i < 6; i++) b[i] = (byte) (ms >>> (8 * (5 - i)));
        b[6] = (byte) ((b[6] & 0x0f) | 0x70);
        b[8] = (byte) ((b[8] & 0x3f) | 0x80);
        StringBuilder h = new StringBuilder();
        for (byte x : b) h.append(String.format("%02x", x));
        return h.substring(0, 8) + "-" + h.substring(8, 12) + "-" + h.substring(12, 16) + "-" + h.substring(16, 20) + "-" + h.substring(20);
    }

    static synchronized JSONObject read(Context c, String id) {
        try {
            File f = meta(c, id);
            if (!f.exists()) return null;
            return new JSONObject(new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    static synchronized void write(Context c, JSONObject o) {
        try {
            String id = o.getString("id");
            File tmp = new File(dir(c), id + ".json.tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(o.toString().getBytes(StandardCharsets.UTF_8));
            }
            tmp.renameTo(meta(c, id));
        } catch (Exception ignored) {
        }
    }

    /** Read, change, write as one step: the bubble and the upload worker update the same item. */
    static synchronized void update(Context c, String id, String key, Object value) {
        JSONObject o = read(c, id);
        if (o == null) return;
        try {
            o.put(key, value);
        } catch (JSONException ignored) {
        }
        write(c, o);
    }

    static List<JSONObject> all(Context c) {
        List<JSONObject> out = new ArrayList<>();
        File[] files = dir(c).listFiles((d, n) -> n.endsWith(".json"));
        if (files == null) return out;
        for (File f : files) {
            JSONObject o = read(c, f.getName().replace(".json", ""));
            if (o != null) out.add(o);
        }
        Collections.sort(out, (a, b) -> Long.compare(a.optLong("createdAt"), b.optLong("createdAt")));
        return out;
    }

    /** After pairing again, notes parked on a refused token get another go. */
    static synchronized void unpark(Context c) {
        for (JSONObject o : all(c)) {
            int status = o.optInt("status", 0);  // 401 (token) or 404 (farm not on that brain): pairing again can fix both
            if (!o.optBoolean("permanent", false) || (status != 401 && status != 404 && !o.optString("error", "").contains("pair again"))) continue;
            try {
                o.put("permanent", false);
                o.put("state", "saved");
                o.put("error", "");
            } catch (JSONException ignored) {
            }
            write(c, o);
        }
    }

    static void forget(Context c, String id) {
        audio(c, id).delete();
        meta(c, id).delete();
    }

    /** This phone was removed from the business (ADR 0014): its recordings, its pairing and its token go. The web
     *  layer has already handed in what the brain would still take. */
    static void wipe(Context c) {
        File[] files = dir(c).listFiles();
        if (files != null) for (File f : files) f.delete();
        prefs(c).edit().clear().apply();
    }

    /** Uploaded notes are kept in the list for a day, then forgotten. */
    static void prune(Context c) {
        long cut = System.currentTimeMillis() - 24L * 3600 * 1000;
        for (JSONObject o : all(c)) {
            if ("uploaded".equals(o.optString("state")) && o.optLong("createdAt") < cut) forget(c, o.optString("id"));
        }
    }
}
