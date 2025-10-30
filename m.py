#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil
import tempfile
import asyncio
import time
import zipfile

# ---------------------- AUTO-INSTALL DEPENDENCIES ----------------------
REQUIRED = [
    "pyrogram", "tgcrypto", "rarfile", "py7zr", "pyzipper", "pyminizip"
]

def ensure_installed(pkg):
    try:
        __import__(pkg)
    except ImportError:
        print(f"📦 Installing missing package: {pkg} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg, "--upgrade", "--no-cache-dir"])

for p in REQUIRED:
    ensure_installed(p)

# ----------------------------------------------------------------------
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import RPCError
import rarfile, py7zr, pyzipper, pyminizip

# ---------- CONFIG ----------
BOT_TOKEN = "7987360273:AAGPodcENeKnk8eT2qdPQUa4tj0XwJ5n2Ps"
API_ID = 14029127
API_HASH = "72cac79d6c73536769b2f5ed08cebe4f"
# ----------------------------------------------------------------------

app = Client("zipunzip_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------- Utilities ----------
def human_size(n):
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"

async def edit_progress(msg: Message, prefix: str, received: int, total: int, started_at: float):
    elapsed = max(time.time() - started_at, 0.001)
    speed = received / elapsed
    pct = f"{(received/total*100):.1f}%" if total else "?"
    txt = (f"{prefix}\n"
           f"{human_size(received)} / {human_size(total)} ({pct})\n"
           f"⚡ {human_size(speed)}/s | ⏱ {int(elapsed)}s")
    try:
        await msg.edit(txt)
    except RPCError:
        pass

def make_progress_callback(msg, prefix):
    started = time.time()
    last_edit = {"t": 0}
    async def progress(current, total):
        now = time.time()
        if now - last_edit["t"] < 1 and current != total:
            return
        last_edit["t"] = now
        await edit_progress(msg, prefix, current, total, started)
    return progress

# ---------- Extraction ----------
def try_extract(archive_path, dest_dir, password=None):
    ext = archive_path.lower()
    try:
        if ext.endswith(".zip"):
            try:
                with pyzipper.AESZipFile(archive_path) as z:
                    if password:
                        z.pwd = password.encode()
                    z.extractall(dest_dir)
                return True, "✅ Extracted ZIP successfully"
            except Exception:
                pass
            try:
                with zipfile.ZipFile(archive_path) as z:
                    if password:
                        z.extractall(dest_dir, pwd=password.encode())
                    else:
                        z.extractall(dest_dir)
                return True, "✅ Extracted ZIP"
            except Exception as e:
                return False, str(e)

        elif ext.endswith(".7z"):
            with py7zr.SevenZipFile(archive_path, mode='r', password=password) as a:
                a.extractall(path=dest_dir)
            return True, "✅ Extracted 7Z"

        elif ext.endswith(".rar"):
            rf = rarfile.RarFile(archive_path)
            if password:
                rf.extractall(dest_dir, pwd=password)
            else:
                rf.extractall(dest_dir)
            return True, "✅ Extracted RAR"

        elif ext.endswith((".tar", ".gz", ".bz2", ".xz")):
            import tarfile
            with tarfile.open(archive_path, "r:*") as tar:
                tar.extractall(dest_dir)
            return True, "✅ Extracted TAR/GZ"
        else:
            return False, "❌ Unknown format"
    except Exception as e:
        return False, f"❌ Extraction failed: {e}"

# ---------- Handlers ----------
@app.on_message(filters.command("start"))
async def start_cmd(_, m):
    await m.reply_text(
        "👋 **Welcome to Zip/Unzip Bot!**\n\n"
        "📦 Send me any archive (.zip, .7z, .rar, .tar.gz, etc.)\n"
        "🔑 If it has a password, reply `/password yourpass`\n"
        "🧩 I’ll extract and return the files!\n\n"
        "To zip files:\n`/zip password=pass name=file.zip`"
    )

password_store = {}

@app.on_message(filters.command("password"))
async def password_cmd(_, m):
    if not m.reply_to_message:
        return await m.reply_text("⚠️ Reply to the archive with `/password yourpass`")
    pw = " ".join(m.command[1:]) or None
    if not pw:
        return await m.reply_text("⚠️ Provide a password: `/password mypass123`")
    password_store[m.reply_to_message.id] = pw
    await m.reply_text("🔐 Password saved for that file!")

# ---------- MAIN UNZIP HANDLER ----------
@app.on_message(filters.document)
async def handle_doc(c, m):
    doc = m.document
    name = doc.file_name
    size = doc.file_size or 0
    msg = await m.reply_text(f"⬇️ Downloading **{name}** ({human_size(size)})...")

    temp = tempfile.mkdtemp(prefix="tgzip_")
    path = os.path.join(temp, name)
    pw = password_store.pop(m.id, None)

    try:
        await c.download_media(m, path, progress=make_progress_callback(msg, f"Downloading {name}"))
    except Exception as e:
        await msg.edit(f"❌ Download failed: {e}")
        shutil.rmtree(temp)
        return

    await msg.edit("📂 Extracting...")
    ok, out = try_extract(path, os.path.join(temp, "out"), pw)
    if not ok:
        await msg.edit(out)
        shutil.rmtree(temp)
        return

    out_dir = os.path.join(temp, "out")
    files = []
    for root, _, fns in os.walk(out_dir):
        for f in fns:
            files.append(os.path.join(root, f))

    if not files:
        await msg.edit("❌ No files found inside the archive.")
        shutil.rmtree(temp)
        return

    await msg.edit(f"✅ Extracted {len(files)} file(s). Sending one by one...")

    sent_count = 0
    for fpath in files:
        fname = os.path.basename(fpath)
        try:
            await c.send_document(m.chat.id, fpath)
            sent_count += 1
            await asyncio.sleep(1)
        except Exception as e:
            await m.reply_text(f"⚠️ Failed to send {fname}: {e}")

    await msg.edit(f"📤 Sent {sent_count} file(s) successfully!")
    shutil.rmtree(temp)

# ---------- ZIP CREATION HANDLER ----------
@app.on_message(filters.command("zip"))
async def zip_cmd(c, m):
    params = {}
    for token in m.text.split():
        if "=" in token:
            k, v = token.split("=", 1)
            params[k.lower()] = v
    pw = params.get("password")
    name = params.get("name", f"archive_{int(time.time())}.zip")

    if not m.reply_to_message or not m.reply_to_message.document:
        return await m.reply_text("⚠️ Reply to a file or document to zip it.")

    msg = await m.reply_text("⬇️ Downloading file for ZIP...")
    temp = tempfile.mkdtemp(prefix="tgzip_")
    doc = m.reply_to_message.document
    path = os.path.join(temp, doc.file_name)

    await c.download_media(m.reply_to_message, path, progress=make_progress_callback(msg, f"Downloading {doc.file_name}"))
    out_path = os.path.join(temp, name)

    try:
        if pw:
            pyminizip.compress(path, None, out_path, pw, 5)
        else:
            with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.write(path, arcname=doc.file_name)
    except Exception as e:
        await msg.edit(f"❌ ZIP creation failed: {e}")
        shutil.rmtree(temp)
        return

    upmsg = await msg.edit("⬆️ Uploading ZIP file...")
    await c.send_document(m.chat.id, out_path, progress=make_progress_callback(upmsg, f"Uploading {name}"))
    await upmsg.delete()
    shutil.rmtree(temp)

# ---------- START BOT ----------
if __name__ == "__main__":
    print("🚀 Starting Telegram Zip/Unzip Bot...")
    app.run()
