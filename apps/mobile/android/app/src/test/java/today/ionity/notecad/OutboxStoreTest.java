// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;

import org.json.JSONObject;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

import java.io.File;
import java.util.List;

/** The bubble's outbox on the phone's own storage: what survives, what gets another go, what is forgotten. */
@RunWith(RobolectricTestRunner.class)
public class OutboxStoreTest {
    private Context ctx;

    @Before
    public void setUp() {
        ctx = ApplicationProvider.getApplicationContext();
        File[] old = OutboxStore.dir(ctx).listFiles();
        if (old != null) for (File f : old) f.delete();
    }

    private static JSONObject item(String id, long createdAt, String state) throws Exception {
        return new JSONObject().put("id", id).put("createdAt", createdAt).put("state", state);
    }

    @Test
    public void writesReadsAndUpdatesOneItem() throws Exception {
        OutboxStore.write(ctx, item("a", 1, "saved"));
        OutboxStore.update(ctx, "a", "state", "uploading");
        JSONObject o = OutboxStore.read(ctx, "a");
        assertEquals("uploading", o.getString("state"));
        assertFalse(new File(OutboxStore.dir(ctx), "a.json.tmp").exists());  // written whole, then renamed
        OutboxStore.update(ctx, "missing", "state", "x");                    // nothing to update: nothing made
        assertNull(OutboxStore.read(ctx, "missing"));
    }

    @Test
    public void listsOldestFirst() throws Exception {
        OutboxStore.write(ctx, item("late", 300, "saved"));
        OutboxStore.write(ctx, item("early", 100, "saved"));
        OutboxStore.write(ctx, item("mid", 200, "saved"));
        List<JSONObject> all = OutboxStore.all(ctx);
        assertEquals("early", all.get(0).getString("id"));
        assertEquals("late", all.get(2).getString("id"));
    }

    @Test
    public void pairingAgainUnparksTokenAndFarmRefusals() throws Exception {
        OutboxStore.write(ctx, item("token", 1, "failed").put("permanent", true).put("status", 401));
        OutboxStore.write(ctx, item("farm", 2, "failed").put("permanent", true).put("status", 404));
        OutboxStore.write(ctx, item("broken", 3, "failed").put("permanent", true).put("status", 400)
                .put("error", "The brain answered 400"));
        OutboxStore.unpark(ctx);
        assertEquals("saved", OutboxStore.read(ctx, "token").getString("state"));
        assertFalse(OutboxStore.read(ctx, "farm").getBoolean("permanent"));
        assertTrue(OutboxStore.read(ctx, "broken").getBoolean("permanent"));  // pairing cannot fix a bad file
    }

    @Test
    public void forgetsUploadedNotesAfterADay() throws Exception {
        long now = System.currentTimeMillis();
        OutboxStore.write(ctx, item("old", now - 25L * 3600 * 1000, "uploaded"));
        OutboxStore.write(ctx, item("new", now - 3600 * 1000, "uploaded"));
        OutboxStore.write(ctx, item("waiting", now - 48L * 3600 * 1000, "saved"));  // never uploaded: kept
        OutboxStore.prune(ctx);
        assertNull(OutboxStore.read(ctx, "old"));
        assertTrue(OutboxStore.read(ctx, "new") != null && OutboxStore.read(ctx, "waiting") != null);
    }

    @Test
    public void captureIdsAreVersion7AndTimeOrdered() throws Exception {
        String a = OutboxStore.uuid7();
        Thread.sleep(2);
        String b = OutboxStore.uuid7();
        assertTrue(a.matches("[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"));
        assertTrue(a.compareTo(b) < 0);
    }

    @Test
    public void aRevokedPhoneWipesItsOutboxAndPairing() throws Exception {
        OutboxStore.write(ctx, item("w1", 1, "saved"));
        OutboxStore.audio(ctx, "w1").createNewFile();
        OutboxStore.prefs(ctx).edit().putString("token", "nct_x").putString("url", "http://brain").commit();
        OutboxStore.wipe(ctx);
        assertTrue(OutboxStore.all(ctx).isEmpty());
        assertFalse(OutboxStore.audio(ctx, "w1").exists());
        assertEquals("", OutboxStore.prefs(ctx).getString("token", ""));
    }
}
