// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.annotation.SuppressLint;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.TextView;

import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/** The floating capture bubble: a foreground service (type microphone) with a draggable overlay button.
 *  Tap to record, tap again to save; the note goes into the outbox and WorkManager sends it with tus.
 *  Without the overlay permission the notification's Record/Stop button does the same. */
public class BubbleService extends Service {
    static volatile boolean running = false;
    static final String CHANNEL = "notecad-capture";
    static final int NOTE_ID = 7001;
    static final String ACT_TOGGLE = "today.ionity.notecad.TOGGLE";
    static final String ACT_CLOSE = "today.ionity.notecad.CLOSE";
    private static final String TAG = "NoteCadBubble";

    private WindowManager wm;
    private TextView bubble;
    private MediaRecorder recorder;
    private String recId;
    private long recStart;
    private String recordedAt;

    @Override public IBinder onBind(Intent i) { return null; }

    @Override
    public void onCreate() {
        super.onCreate();
        running = true;
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26 && nm.getNotificationChannel(CHANNEL) == null) {
            NotificationChannel ch = new NotificationChannel(CHANNEL, "NoteCad capture", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("Shows while the NoteCad bubble is ready to record");
            nm.createNotificationChannel(ch);
        }
        try {
            startInForeground();
        } catch (RuntimeException ex) {
            // Android 14+: a microphone service may only start while NoteCad is on screen
            Log.w(TAG, "not allowed to start in the background", ex);
            stopSelf();
            return;
        }
        if (Build.VERSION.SDK_INT < 23 || Settings.canDrawOverlays(this)) showBubble();
    }

    private void startInForeground() {
        Notification n = buildNotification();
        if (Build.VERSION.SDK_INT >= 30) startForeground(NOTE_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
        else startForeground(NOTE_ID, n);
    }

    private Notification buildNotification() {
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
        PendingIntent toggle = PendingIntent.getService(this, 1, new Intent(this, BubbleService.class).setAction(ACT_TOGGLE), flags);
        PendingIntent close = PendingIntent.getService(this, 2, new Intent(this, BubbleService.class).setAction(ACT_CLOSE), flags);
        PendingIntent open = PendingIntent.getActivity(this, 3,
            new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP), flags);
        boolean rec = recorder != null;
        return new NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(rec ? "Recording a NoteCad note" : "NoteCad is ready")
            .setContentText(rec ? "Tap Stop to save it to the outbox" : "Tap the bubble or Record to capture a note")
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .addAction(0, rec ? "Stop" : "Record", toggle)
            .addAction(0, "Close", close)
            .build();
    }

    private void refreshNotification() {
        getSystemService(NotificationManager.class).notify(NOTE_ID, buildNotification());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String a = intent != null ? intent.getAction() : null;
        if (ACT_TOGGLE.equals(a)) toggle();
        else if (ACT_CLOSE.equals(a)) stopSelf();
        return START_NOT_STICKY;  // never restarted from the background: Android would refuse the microphone
    }

    @SuppressLint("ClickableViewAccessibility")
    private void showBubble() {
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);
        int size = (int) (64 * getResources().getDisplayMetrics().density);
        bubble = new TextView(this);
        bubble.setText("🎙");
        bubble.setTextSize(26);
        bubble.setGravity(Gravity.CENTER);
        bubble.setContentDescription("Record a NoteCad note");
        paintBubble();
        int type = Build.VERSION.SDK_INT >= 26 ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY : WindowManager.LayoutParams.TYPE_PHONE;
        WindowManager.LayoutParams lp = new WindowManager.LayoutParams(size, size, type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.x = 24;
        lp.y = 300;
        bubble.setOnTouchListener(new View.OnTouchListener() {
            int sx, sy; float tx, ty; long down; boolean moved;
            @Override public boolean onTouch(View v, MotionEvent e) {
                switch (e.getAction()) {
                    case MotionEvent.ACTION_DOWN:
                        sx = lp.x; sy = lp.y; tx = e.getRawX(); ty = e.getRawY(); down = SystemClock.uptimeMillis(); moved = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        int dx = (int) (e.getRawX() - tx), dy = (int) (e.getRawY() - ty);
                        if (Math.abs(dx) > 12 || Math.abs(dy) > 12) moved = true;
                        if (moved) { lp.x = sx + dx; lp.y = sy + dy; wm.updateViewLayout(bubble, lp); }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (!moved) {
                            if (SystemClock.uptimeMillis() - down > 800) stopSelf();  // long press closes the bubble
                            else toggle();
                        }
                        return true;
                }
                return false;
            }
        });
        try { wm.addView(bubble, lp); } catch (RuntimeException ex) { Log.w(TAG, "overlay refused", ex); bubble = null; }
    }

    private void paintBubble() {
        if (bubble == null) return;
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.OVAL);
        d.setColor(recorder != null ? 0xEEE11D48 : 0xEE0EA5E9);
        d.setStroke(3, 0x66FFFFFF);
        bubble.setBackground(d);
        bubble.setText(recorder != null ? "■" : "🎙");
    }

    private void toggle() {
        if (recorder == null) startRecording(); else stopRecording(true);
        paintBubble();
        refreshNotification();
        buzz();
    }

    private void buzz() {
        try {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v == null) return;
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(40, VibrationEffect.DEFAULT_AMPLITUDE));
            else v.vibrate(40);
        } catch (RuntimeException ignored) { }
    }

    private static String isoNow() {
        SimpleDateFormat f = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        f.setTimeZone(TimeZone.getTimeZone("UTC"));
        return f.format(new Date());
    }

    private void startRecording() {
        recId = OutboxStore.uuid7();
        File out = OutboxStore.audio(this, recId);
        recordedAt = isoNow();
        recStart = System.currentTimeMillis();
        MediaRecorder r = Build.VERSION.SDK_INT >= 31 ? new MediaRecorder(this) : new MediaRecorder();
        try {
            r.setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION);
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
            r.setAudioSamplingRate(16000);
            r.setAudioChannels(1);
            r.setAudioEncodingBitRate(32000);
            r.setOutputFile(out.getAbsolutePath());
            r.prepare();
            r.start();
            recorder = r;
        } catch (Exception ex) {
            Log.e(TAG, "could not start recording", ex);
            r.release();
            out.delete();
            recorder = null;
        }
    }

    private void stopRecording(boolean keep) {
        MediaRecorder r = recorder;
        recorder = null;
        if (r == null) return;
        File out = OutboxStore.audio(this, recId);
        boolean ok = true;
        try { r.stop(); } catch (RuntimeException ex) { ok = false; }  // stop() throws when nothing was recorded
        r.release();
        if (!keep || !ok || System.currentTimeMillis() - recStart < 600 || !out.exists() || out.length() < 1024) {
            out.delete();
            return;
        }
        try {
            JSONObject m = new JSONObject();
            m.put("id", recId);
            m.put("state", "saved");
            m.put("progress", 0);
            m.put("size", out.length());
            m.put("createdAt", System.currentTimeMillis());
            m.put("recordedAt", recordedAt);
            m.put("mime", "audio/mp4");
            m.put("source", "android-bubble");
            OutboxStore.write(this, m);
        } catch (Exception ex) {
            Log.e(TAG, "could not save outbox entry", ex);
            return;
        }
        NoteCadPlugin.outboxChanged();
        UploadWorker.enqueue(this);
    }

    @Override
    public void onDestroy() {
        stopRecording(true);
        if (bubble != null && wm != null) { try { wm.removeView(bubble); } catch (RuntimeException ignored) { } }
        bubble = null;
        running = false;
        super.onDestroy();
    }
}
