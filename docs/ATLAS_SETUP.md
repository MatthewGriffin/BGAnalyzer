# MongoDB-only setup

MongoDB Atlas is the sole remote source for today's readings, history, treatment records and profile stores. Nightscout connection controls and automatic HTTP fallback have been removed. Existing cache identities and keyring entries are retained internally for compatibility; old Nightscout settings in config.json are not used to contact the site.

1. Create a dedicated Atlas database user with the **read** role on database **Cluster0**, and allow this computer's public IP in Atlas Network Access.
2. Copy the `mongodb+srv://` connection URI from Atlas **Connect → Drivers**, replacing its credentials with the read-only database user's credentials. Percent-encode reserved characters in the username/password.
3. Restart BGAnalyzer, open **Connection**, enter database **Cluster0** and the URI in the password field. Leave the URI blank to reuse the existing keyring credential. Select keyring storage to retain a newly entered URI after restart.
4. Verify the collection names (`entries`, `treatments`, `devicestatus`, `profile`) and click **Save connection and import**. A missing URI or failed database read produces an error; the app does not fall back to Nightscout.

Automatic polling reads today from local midnight through MongoDB. Manual imports read the chosen history range through the same database. Status messages explicitly identify MongoDB. Existing checked history windows can be reused; select **Recheck previously imported history** to re-read them from MongoDB.

The minute poll fetches only documents inserted since the last fully successful poll (with a one-hour overlap for mid-scan commits and clock skew), using the indexed document id instead of scanning the collection. Manual and forced imports always scan the requested span fully. A correction made on the server to an already-imported record therefore appears after the next manual import or history recheck, not necessarily after the next automatic poll.

## Daily graph

Use **Previous day**, **Next day**, the date picker, or **Today** to navigate cached days. Local-time day boundaries account for 23/25-hour daylight-saving days. The report period independently controls summaries, treatment records and exports. Browsing a graph day does not download it automatically; import a sufficiently large history range if needed.

## Implementation and verification limits

Historical collections use MongoDB cursors with batches of 1,000, eliminating HTTP exclusion probes. Imports retain per-window transactions, remote IDs, disappearance tracking and revision invalidation. Each requested span is fetched once in week-long chunks rather than once per day: the treatments/devicestatus date filters convert stored timestamp spellings server-side and cannot use an ordinary index, so per-day queries would rescan the whole collection for every day. Journaling still checkpoints every day window, so interrupted imports resume where they stopped. MongoDB cursors are not a point-in-time database snapshot; concurrent upstream edits are reconciled in later imports. BSON ObjectIds and dates are normalized to JSON-compatible values. Treatment/device timestamps are converted to dates in MongoDB so different ISO offsets/fraction spellings do not silently omit boundary records. Live Atlas speed has not been benchmarked.

The app checks collection existence to avoid treating typos as empty history. A successfully queried range still does not prove complete uploads, sensor coverage, treatment delivery or profile activation. Numerical tuning and AI recommendations remain unavailable. Synthetic tests cover routing, cursor batches, cancellation, rollback, secret isolation, local-day boundaries and graph navigation. Live Atlas access remains unverified until the user supplies the URI in the app.

References: [Atlas database users](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/), [PyMongo find/cursors](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/crud/query/find/), [PyMongo TLS](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/security/tls/).
