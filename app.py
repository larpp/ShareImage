# app.py (LOCAL STORAGE MODE, no camera input)
# Streamlit photo sharing for 6 people — saves files under ./uploads/{name}/{album}
# No Supabase/S3 required. Keep this server running so others can upload/download.
#
# Setup
# 1) pip install -r requirements.txt
# 2) streamlit run app.py
#
# requirements.txt (example)
# streamlit>=1.37
# pillow
# pillow-heif  # optional, for HEIC support on iPhone

import io
import os
import zipfile
from datetime import datetime
from typing import List, Tuple

import streamlit as st
from PIL import Image

# --- Optional HEIC support
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

# ------------------------------
# App Config & Constants
# ------------------------------
st.set_page_config(page_title="Photo Share (6 people)", page_icon="📸", layout="wide")

# Root folder for local storage
BASE_DIR = os.path.abspath("uploads")
os.makedirs(BASE_DIR, exist_ok=True)

# --- Simple password gate (all 6 people share one password)
PASS = os.getenv("APP_PASS") or "eggmongol"
try:
    # If secrets.toml is configured, allow override
    if hasattr(st, "secrets") and isinstance(st.secrets, dict) and "APP_PASS" in st.secrets:
        PASS = st.secrets["APP_PASS"]
except Exception:
    pass

if "authed" not in st.session_state:
    st.session_state.authed = False

# Allow passing password via query param ?p=...
try:
    qparams = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
    qp_pass = None
    if isinstance(qparams, dict):
        qp_val = qparams.get("p")
        qp_pass = qp_val[0] if isinstance(qp_val, list) else qp_val
    if qp_pass and qp_pass == PASS:
        st.session_state.authed = True
except Exception:
    pass

if not st.session_state.authed:
    st.header("🔒 Enter Password")
    pw = st.text_input("Password", type="password")
    if st.button("Unlock"):
        if pw == PASS:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Wrong password. Try again.")
    st.stop()

# ------------------------------
# Sidebar: identity
# ------------------------------
st.sidebar.header("👤 Who are you?")
user = st.sidebar.text_input("Your name (e.g., Jiho)", max_chars=24).strip()
if not user:
    st.sidebar.info("Type your name so your uploads are grouped correctly.")

# ------------------------------
# Tabs
# ------------------------------
tab_upload, tab_browse = st.tabs(["Upload", "Browse & Download"]) 

# Utility: ensure album folder

def ensure_album_folder(u: str, a: str) -> str:
    folder = os.path.join(BASE_DIR, u, a)
    os.makedirs(folder, exist_ok=True)
    return folder

# ------------------------------
# Upload Tab
# ------------------------------
with tab_upload:
    st.header("Upload photos to an album")
    colA, colB = st.columns([1,1])

    with colA:
        album = st.text_input("Album name (e.g., 'Day1-Camping')", placeholder="Enter or select an album name")
        if not album:
            st.caption("Tip: keep album names short (letters, numbers, dashes)")

        st.markdown("**Pick from your phone gallery** (multiple files)")
        files = st.file_uploader(
            "Choose photos", type=["jpg","jpeg","png","heic","webp"], accept_multiple_files=True
        )

        if st.button("⬆️ Upload", type="primary", disabled=not (user and album and files)):
            uploaded = 0
            bundle: List[Tuple[str, bytes]] = []

            # Multiple files from gallery
            for f in files or []:
                name = f.name
                try:
                    data = f.read()
                except Exception:
                    data = f.getvalue()
                # Normalize to JPEG for consistent preview/orientation
                try:
                    img = Image.open(io.BytesIO(data))
                    rgb = img.convert("RGB")
                    buf = io.BytesIO()
                    rgb.save(buf, format="JPEG", quality=90, optimize=True)
                    data = buf.getvalue()
                    name = os.path.splitext(name)[0] + ".jpg"
                except Exception:
                    pass
                bundle.append((name, data))

            # Local save
            with st.spinner("Saving..."):
                folder = ensure_album_folder(user, album)
                for name, data in bundle:
                    path = os.path.join(folder, name)
                    try:
                        with open(path, "wb") as f:
                            f.write(data)
                        uploaded += 1
                    except Exception as e:
                        st.error(f"Failed: {name} — {e}")
            st.success(f"Uploaded {uploaded} file(s) to {user}/{album}")

    with colB:
        st.subheader("What others will see")
        st.caption("Below is how your album appears to everyone")
        if user and album:
            thumbs = []
            folder = os.path.join(BASE_DIR, user, album)
            if os.path.isdir(folder):
                for fname in sorted(os.listdir(folder)):
                    if fname.startswith("."):
                        continue
                    thumbs.append(os.path.join(folder, fname))
            if thumbs:
                st.image(thumbs, width=150)
            else:
                st.info("No images yet. Upload on the left and they will show here.")
        else:
            st.info("Enter your name and album to preview.")

# ------------------------------
# Browse & Download Tab
# ------------------------------
with tab_browse:
    st.header("Browse everyone's albums")

    # List people (top-level dirs)
    users: List[str] = []
    for entry in sorted(os.listdir(BASE_DIR)):
        if os.path.isdir(os.path.join(BASE_DIR, entry)):
            users.append(entry)

    if not users:
        st.info("No uploads yet. Albums will appear here.")
    else:
        u = st.selectbox("Select a person", options=users)
        u_dir = os.path.join(BASE_DIR, u)
        albums = [d for d in sorted(os.listdir(u_dir)) if os.path.isdir(os.path.join(u_dir, d))]
        if albums:
            a = st.selectbox("Select an album", options=albums)
            folder = os.path.join(BASE_DIR, u, a)
            files = [f for f in sorted(os.listdir(folder)) if os.path.isfile(os.path.join(folder, f))]

            cols = st.columns(4)
            images = []  # (fname, fullpath)
            for i, fname in enumerate(files):
                fpath = os.path.join(folder, fname)
                images.append((fname, fpath))
                cols[i % 4].image(fpath, caption=fname, use_container_width=True)

            # Download ZIP of this album
            if images:
                if st.button("⬇️ Download this album as ZIP"):
                    zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for fname, fullpath in images:
                            try:
                                with open(fullpath, "rb") as f:
                                    zf.writestr(fname, f.read())
                            except Exception as e:
                                st.error(f"Failed to add {fname}: {e}")
                    zip_buf.seek(0)
                    st.download_button(
                        label="Download ZIP",
                        data=zip_buf,
                        file_name=f"{u}_{a}.zip",
                        mime="application/zip",
                    )
        else:
            st.info("No albums for this person yet.")

# --- Footer
st.caption("Local mode: files are stored on this server under ./uploads. Keep the server running for sharing.")
