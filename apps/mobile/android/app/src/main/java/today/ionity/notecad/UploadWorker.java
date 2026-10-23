// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.content.Context;
import android.content.SharedPreferences;

import androidx.annotation.NonNull;
import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONObject;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/** Sends the native outbox to the brain whenever the phone is on a network, even with the app closed.
 *  Android retries with back-off until it gets through; each upload resumes where it stopped. */
public class UploadWorker extends Worker {
    static final String NAME = "notecad-outbox-upload";

    public UploadWorker(@NonNull Context c, @NonNull WorkerParameters p) { super(c, p); }

    static void enqueue(Context c) {
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(UploadWorker.class)
            .setConstraints(new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 20, TimeUnit.SECONDS)
            .build();
        WorkManager.getInstance(c).enqueueUniqueWork(NAME, ExistingWorkPolicy.APPEND_OR_REPLACE, req);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context c = getApplicationContext();
        SharedPreferences p = OutboxStore.prefs(c);
        String url = p.getString("url", ""), token = p.getString("token", ""), ws = p.getString("ws", "");
        if (url.isEmpty() || ws.isEmpty()) return Result.success();  // not paired yet: the notes wait
        boolean retry = false;
        for (JSONObject o : OutboxStore.all(c)) {
            String state = o.optString("state");
            if (!state.equals("saved") && !state.equals("failed") && !state.equals("uploading")) continue;
            if (o.optBoolean("permanent", false)) continue;
            String id = o.optString("id");
            File audio = OutboxStore.audio(c, id);
            if (!audio.exists()) {
                OutboxStore.update(c, id, "state", "failed");
                OutboxStore.update(c, id, "error", "The recording is missing on this phone");
                continue;
            }
            OutboxStore.update(c, id, "state", "uploading");
            NoteCadPlugin.outboxChanged();
            Map<String, String> meta = new LinkedHashMap<>();
            meta.put("capture_id", id);
            meta.put("filetype", o.optString("mime", "audio/mp4"));
            meta.put("filename", id + ".m4a");
            meta.put("recorded_at", o.optString("recordedAt"));
            meta.put("source", o.optString("source", "android-bubble"));
            String existing = o.optString("uploadUrl", "");
            try {
                TusUploader.Result r = TusUploader.upload(url + "/api/v1/workspaces/" + ws + "/uploads", token, audio, meta,
                    existing.isEmpty() ? null : existing,
                    u -> OutboxStore.update(c, id, "uploadUrl", u),
                    (sent, total) -> { OutboxStore.update(c, id, "progress", total > 0 ? (double) sent / total : 0); NoteCadPlugin.outboxChanged(); });
                OutboxStore.update(c, id, "state", "uploaded");
                OutboxStore.update(c, id, "progress", 1.0);
                OutboxStore.update(c, id, "error", "");
                if (r.captureId != null) OutboxStore.update(c, id, "captureId", r.captureId);
                audio.delete();  // the brain has it now
            } catch (TusUploader.Rejected e) {
                OutboxStore.update(c, id, "state", "failed");
                OutboxStore.update(c, id, "error", e.getMessage());
                if (e.status == 401 || e.status == 413 || e.status == 400) OutboxStore.update(c, id, "permanent", true);
                else retry = true;
            } catch (Exception e) {
                OutboxStore.update(c, id, "state", "failed");
                OutboxStore.update(c, id, "error", "Upload paused: no connection to the brain");
                retry = true;
            }
            NoteCadPlugin.outboxChanged();
        }
        OutboxStore.prune(c);
        return retry ? Result.retry() : Result.success();
    }
}
