<!--
  Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
  Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
  Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
  Web: https://www.ionity.today | Ref: https://www.ionity.co.za
-->

# POPIA: what needs a person to decide

The code does what it can (see [popia-action-register.md](popia-action-register.md)). These need a human or a legal
decision, so the code does not take them. Technical compliance check, not legal advice: have a POPIA practitioner
confirm the items marked **legal**.

| # | What | Who | Why |
|---|---|---|---|
| 1 | <a id="officer"></a>Register Ionity Global's Information Officer (and any deputy) with the Information Regulator; publish Ionity's PAIA manual | Ionity (Dennis / Johan) | s55-56 and PAIA s51. IBMM's notice names each business's own officer (the owner by default); Ionity needs its own as a supplier and future operator |
| 2 | <a id="operators"></a>Sign operator agreements (s20-21) with Anthropic, Deepgram, Supabase and Google (Drive), and keep them on file; check each one's retention, training use and region; choose a Supabase region (South Africa or an adequate one) | Ionity | Nothing goes to Anthropic or Deepgram until an owner turns the cloud transfer on; when Ionity runs an edge node or Supabase for a farm, Ionity is that farm's operator and needs a written agreement with it too (security measures, breach duty) |
| 3 | <a id="lawful-basis"></a>**legal** Write the lawful basis per purpose for the notice (s11): recording employees' work notes (the employment contract / the business's legitimate interest), naming third parties in notes, sending notes abroad (consent or a binding agreement, s72) | Ionity with a practitioner | Choosing this wording commits Ionity to a legal position, so the code does not choose it. The notice now says what, why, who, where and how long; the basis line is what is missing |
| 4 | <a id="notice"></a>**legal** Review the privacy notice text (desktop `PrivacyNotice.tsx`, phone `PrivacySheet.tsx`, version 2) and the employee monitoring paragraph | Ionity with a practitioner | s18 lists what a notice must say; the text is plain-language and complete as far as the code knows, not reviewed by a lawyer |
| 5 | <a id="retention-real"></a>Set retention periods on the real workspaces (the owner, in the notice). Suggested: recordings 90 days, transcripts 365, activity log 365 | Each farm owner (Dennis for the showcase farms) | Nothing is deleted until an owner sets them; setting them on a real workspace deletes older data, so the code waits for the owner |
| 6 | <a id="archive"></a>Choose `NC_BRAIN_ARCHIVE_DAYS` for `data\archive` on WABAKIPI (backups before big changes, removed workspaces). Today 74 MB+ is kept with no end date | Dennis | The archives are backups the project rules ask for; how long to keep them is a decision, and turning it on deletes the older ones |
| 7 | <a id="disk"></a>Encrypt the disk that holds `data\` on WABAKIPI: Windows 11 Home has no BitLocker (the status table shows `WARN`); use Device Encryption if the PC supports it, or Windows Pro with BitLocker | Dennis | s19. The database and recordings are plain files; only Windows sign-in protects them |
| 8 | <a id="lora"></a>Decide whether per-owner LoRA training on the owner's own conversations goes ahead (`/train/export`; no adapter has been trained yet) and say so in the notice if it does | Ionity | s15: training is a further purpose. The examples are the owner's own, kept in their own store and wiped with it; employees' words are in their own stores and are not exported for training |
| 9 | <a id="breach"></a>Own the breach runbook ([breach-runbook.md](breach-runbook.md)): who decides it is a breach, who tells the Regulator and the people affected, the Regulator's form | Ionity and each farm owner | s22: the code logs what is needed to find and scope a breach; telling people is a human act |
| 10 | <a id="cloud"></a>Turn the cloud transfer on for a workspace only after items 2 and 3 | The farm owner | s72. Off by default; the owner's tick is logged |
| 11 | <a id="children"></a>Confirm no children use the app (farm workers under 18) | Each farm owner | s34-35: the app does not collect ages; the notice does not invite children |
