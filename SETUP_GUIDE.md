# Setup Guide: Connect the Slideshow to Your Google Form

This is a ONE-TIME setup. After this, you just run one command each month.

---

## Step 1: Create a Google Cloud project (free)

1. Go to https://console.cloud.google.com
2. Click the project dropdown (top left) → **New Project**
3. Name it anything, e.g. "Church Birthday Slideshow" → Create

## Step 2: Enable two APIs

With your new project selected:
1. Go to https://console.cloud.google.com/apis/library
2. Search **"Google Sheets API"** → click it → **Enable**
3. Search **"Google Drive API"** → click it → **Enable**

## Step 3: Create a Service Account (this is the "robot user" that reads your data)

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click **Create Service Account**
3. Name it e.g. "birthday-slideshow-bot" → Create and Continue → skip the optional role/access steps → Done
4. Click on the service account you just created
5. Go to the **Keys** tab → **Add Key** → **Create new key** → choose **JSON** → Create
6. A `.json` file downloads automatically. Rename it to `service_account.json` and put it in the same folder as `birthday_slideshow.py`

⚠️ Treat this JSON file like a password — don't share it or upload it publicly.

## Step 4: Find the service account's email address

Open `service_account.json` in any text editor. Find the line:
```
"client_email": "birthday-slideshow-bot@your-project.iam.gserviceaccount.com"
```
Copy that email — you'll paste it into two "Share" dialogs next.

## Step 5: Share your response Sheet with the service account

1. Open the Google Sheet that collects your Form responses
2. Click **Share** (top right)
3. Paste the service account email from Step 4
4. Set permission to **Viewer** → Send/Share
   (It will warn "this isn't a real inbox" — that's expected, ignore it and confirm)

## Step 6: Share the Drive photo folder with the service account

Google Forms automatically saves uploaded photos into a Drive folder named after your form.

1. Go to your Google Drive → find the folder (search the form's title, or check
   the Form's "Responses" tab settings for a link to it)
2. Right-click the folder → **Share**
3. Paste the same service account email → **Viewer** → Share

## Step 7: Get your Sheet ID

Open the response Sheet — the URL looks like:
```
https://docs.google.com/spreadsheets/d/1AbCDefGhIJKLmnopQRSTuvWXyz1234567890/edit
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ this part
```
Copy that long ID string — that's your `--sheet-id`.

## Step 8: Match the column names

Open `google_sheet_loader.py`, find the `COLUMN_MAP` section near the top,
and change the values on the right to match your Sheet's actual header row
(row 1) exactly, for example:

```python
COLUMN_MAP = {
    "name": "Full Name",
    "day": "Birthday - Day",
    "month": "Birthday - Month",
    "cell_unit": "Which Cell Unit are you part of?",
    "photo": "Upload your photo",
}
```

## Step 9: Install the extra packages

```bash
pip install gspread google-auth google-api-python-client pillow gTTS pyttsx3
```

(ffmpeg must also be installed and on your PATH.)

## Step 10: Run it!

```bash
python birthday_slideshow.py --sheet-id 1AbCDefGhIJKLmnopQRSTuvWXyz1234567890
```

It automatically:
- Defaults to the **current month** (no need to type it, unless you want a
  different month — then add `--month July`)
- Pulls every response, skips blank/incomplete rows automatically
- Downloads each person's uploaded photo from Drive
- Builds the video to `output/birthday_slideshow_<Month>.mp4`

That's it — same command every month, always pulling whatever is currently
in the sheet.

---

### Troubleshooting

- **"PERMISSION_DENIED" errors** → you forgot to Share the Sheet or the Drive
  folder with the service account email (Steps 5 & 6).
- **A person is missing from the video** → check their row: did they leave
  Day, Month, or Name blank? Those rows are skipped with a printed warning
  so you can follow up with them directly.
- **Wrong photo / no photo shows up** → the photo cell must contain the
  Drive link Google Forms generates automatically for file-upload
  questions. Don't manually replace it with a different kind of link.