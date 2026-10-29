// Ionity NoteCad - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** This phone's own token (ADR 0014, decision 19; POPIA review, Keystore): kept encrypted with an AES-GCM key that
 *  lives in the Android Keystore and never leaves it. The app's web layer gets it from here at start and keeps it only
 *  in memory. Where no Keystore exists (unit tests), it is kept as before, marked as plain. */
final class TokenVault {
    private static final String KEY_ALIAS = "notecad-token-key";
    private static final String PREF = "token_enc";
    private static final String LEGACY = "token";

    private TokenVault() {}

    static void write(Context c, String token) {
        SharedPreferences.Editor e = OutboxStore.prefs(c).edit().remove(LEGACY);
        if (token == null || token.isEmpty()) {
            e.remove(PREF).apply();
            return;
        }
        e.putString(PREF, seal(token)).apply();
    }

    static String read(Context c) {
        SharedPreferences p = OutboxStore.prefs(c);
        String v = p.getString(PREF, null);
        if (v == null) {  // written before the vault: move it in
            String old = p.getString(LEGACY, "");
            if (!old.isEmpty()) write(c, old);
            return old;
        }
        return open(v);
    }

    static void clear(Context c) {
        OutboxStore.prefs(c).edit().remove(PREF).remove(LEGACY).apply();
    }

    static String seal(String token) {
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] iv = cipher.getIV();
            byte[] ct = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
            return "ks1:" + Base64.encodeToString(iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP);
        } catch (Exception e) {
            return "plain:" + token;  // no Keystore on this device or in this test
        }
    }

    static String open(String sealed) {
        if (sealed.startsWith("plain:")) return sealed.substring(6);
        try {
            String[] parts = sealed.split(":");
            if (parts.length != 3 || !parts[0].equals("ks1")) return "";
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[1], Base64.NO_WRAP)));
            return new String(cipher.doFinal(Base64.decode(parts[2], Base64.NO_WRAP)), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return "";  // the key is gone (the app's data was cleared): pair again
        }
    }

    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (ks.containsAlias(KEY_ALIAS)) return ((KeyStore.SecretKeyEntry) ks.getEntry(KEY_ALIAS, null)).getSecretKey();
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        g.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build());
        return g.generateKey();
    }
}
