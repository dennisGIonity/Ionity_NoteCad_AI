// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.Manifest;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import org.json.JSONObject;

import java.lang.ref.WeakReference;

/** Bridge between the web app and the native capture bubble + outbox. */
@CapacitorPlugin(
    name = "NoteCad",
    permissions = {
        @Permission(alias = "microphone", strings = { Manifest.permission.RECORD_AUDIO }),
        @Permission(alias = "notifications", strings = { "android.permission.POST_NOTIFICATIONS" }),
    }
)
public class NoteCadPlugin extends Plugin {
    static final String EXTRA_ACTION = "notecad_action";
    private static WeakReference<NoteCadPlugin> current = new WeakReference<>(null);
    private String pendingAction;

    @Override
    public void load() {
        current = new WeakReference<>(this);
        Intent i = getActivity() != null ? getActivity().getIntent() : null;
        if (i != null && i.hasExtra(EXTRA_ACTION)) pendingAction = i.getStringExtra(EXTRA_ACTION);
        OutboxStore.prune(getContext());
        UploadWorker.enqueue(getContext());
    }

    /** Called from the worker and the bubble (any thread) whenever the outbox changes. */
    static void outboxChanged() {
        NoteCadPlugin p = current.get();
        if (p != null) p.notifyListeners("outboxChanged", new JSObject());
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        super.handleOnNewIntent(intent);
        if (intent != null && intent.hasExtra(EXTRA_ACTION)) {
            String a = intent.getStringExtra(EXTRA_ACTION);
            JSObject o = new JSObject();
            o.put("action", a);
            notifyListeners("launchAction", o, true);
        }
    }

    @PluginMethod
    public void configure(PluginCall call) {
        OutboxStore.prefs(getContext()).edit()
            .putString("url", call.getString("url", ""))
            .putString("token", call.getString("token", ""))
            .putString("ws", call.getString("ws", ""))
            .apply();
        OutboxStore.unpark(getContext());
        UploadWorker.enqueue(getContext());
        call.resolve();
    }

    @PluginMethod
    public void overlayAllowed(PluginCall call) {
        JSObject o = new JSObject();
        o.put("allowed", Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(getContext()));
        call.resolve(o);
    }

    @PluginMethod
    public void openOverlaySettings(PluginCall call) {
        Intent i = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + getContext().getPackageName()));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(i);
        call.resolve();
    }

    @PluginMethod
    public void startBubble(PluginCall call) {
        if (getPermissionState("microphone") != PermissionState.GRANTED) {
            requestPermissionForAliases(new String[] { "microphone", "notifications" }, call, "afterPermissions");
            return;
        }
        doStart(call);
    }

    @PermissionCallback
    private void afterPermissions(PluginCall call) {
        if (getPermissionState("microphone") != PermissionState.GRANTED) {
            call.reject("NoteCad needs the microphone to record notes");
            return;
        }
        doStart(call);
    }

    private void doStart(PluginCall call) {
        Intent i = new Intent(getContext(), BubbleService.class);
        ContextCompat.startForegroundService(getContext(), i);
        JSObject o = new JSObject();
        o.put("started", true);
        o.put("overlay", Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(getContext()));
        call.resolve(o);
    }

    @PluginMethod
    public void stopBubble(PluginCall call) {
        getContext().stopService(new Intent(getContext(), BubbleService.class));
        call.resolve();
    }

    @PluginMethod
    public void bubbleRunning(PluginCall call) {
        JSObject o = new JSObject();
        o.put("running", BubbleService.running);
        call.resolve(o);
    }

    @PluginMethod
    public void listOutbox(PluginCall call) {
        JSArray items = new JSArray();
        for (JSONObject m : OutboxStore.all(getContext())) {
            JSObject o = new JSObject();
            o.put("id", m.optString("id"));
            o.put("state", m.optString("state", "saved"));
            o.put("progress", m.optDouble("progress", 0));
            o.put("size", m.optLong("size", 0));
            o.put("createdAt", m.optLong("createdAt", 0));
            o.put("recordedAt", m.optString("recordedAt", ""));
            o.put("source", m.optString("source", "android-bubble"));
            if (m.has("error")) o.put("error", m.optString("error"));
            items.put(o);
        }
        JSObject r = new JSObject();
        r.put("items", items);
        call.resolve(r);
    }

    @PluginMethod
    public void uploadNow(PluginCall call) {
        UploadWorker.enqueue(getContext());
        call.resolve();
    }

    @PluginMethod
    public void forget(PluginCall call) {
        String id = call.getString("id");
        if (id == null || !id.matches("[0-9a-fA-F-]{36}")) { call.reject("bad id"); return; }
        OutboxStore.forget(getContext(), id);
        outboxChanged();
        call.resolve();
    }

    @PluginMethod
    public void consumeLaunchAction(PluginCall call) {
        JSObject o = new JSObject();
        o.put("action", pendingAction);
        pendingAction = null;
        call.resolve(o);
    }
}
