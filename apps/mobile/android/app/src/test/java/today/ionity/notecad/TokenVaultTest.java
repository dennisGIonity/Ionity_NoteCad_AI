// Ionity Business Mind Map (IBMM) - Mobile (Android) | Ionity Global (Pty) Ltd | AEDI
// Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
// Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
package today.ionity.notecad;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;

import android.content.Context;

import androidx.test.core.app.ApplicationProvider;

import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;

/** The phone's token is kept in the vault, never as the old plain "token" preference (ADR 0014 decision 19, POPIA
 *  review). Robolectric has no AndroidKeyStore, so here the vault falls back to its marked plain form; on a phone the
 *  same calls encrypt with a Keystore key. */
@RunWith(RobolectricTestRunner.class)
public class TokenVaultTest {
    private Context ctx;

    @Before
    public void setUp() {
        ctx = ApplicationProvider.getApplicationContext();
        OutboxStore.prefs(ctx).edit().clear().apply();
    }

    @Test
    public void aTokenGoesInAndComesBack() {
        TokenVault.write(ctx, "nct_secret");
        assertEquals("nct_secret", TokenVault.read(ctx));
        assertNull(OutboxStore.prefs(ctx).getString("token", null));  // never the old plain preference
    }

    @Test
    public void aTokenFromBeforeTheVaultMovesIn() {
        OutboxStore.prefs(ctx).edit().putString("token", "nct_old").apply();
        assertEquals("nct_old", TokenVault.read(ctx));
        assertNull(OutboxStore.prefs(ctx).getString("token", null));
        assertEquals("nct_old", TokenVault.read(ctx));
    }

    @Test
    public void unpairingAndWipingLeaveNoToken() {
        TokenVault.write(ctx, "nct_secret");
        TokenVault.write(ctx, "");
        assertEquals("", TokenVault.read(ctx));
        TokenVault.write(ctx, "nct_secret");
        OutboxStore.wipe(ctx);  // a revoked phone
        assertEquals("", TokenVault.read(ctx));
        assertFalse(OutboxStore.prefs(ctx).contains("token_enc"));
    }

    @Test
    public void aSealedValueThatCannotBeOpenedIsEmpty() {
        assertEquals("", TokenVault.open("ks1:not:base64"));
        assertEquals("", TokenVault.open("garbage"));
        assertEquals("x", TokenVault.open(TokenVault.seal("x")));
    }
}
