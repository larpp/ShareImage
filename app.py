# app.py
# Streamlit photo sharing demo for 6 people
# Features
# - People type their name, pick/enter an album name, and upload multiple photos from phone gallery
# - (Mobile) Optional: take a photo with the camera via st.camera_input
# - Photos are stored in Supabase Storage under bucket "photoshare" with path {user}/{album}/{filename}
# - Everyone can browse albums and download an album as a ZIP
#
# Setup
# 1. pip install -r requirements.txt
# 2. Set env vars: SUPABASE_URL, SUPABASE_ANON_KEY (or service key). Create storage bucket "photoshare" (public)
# 3. streamlit run app.py
#
# requirements.txt (example)
# streamlit>=1.37
# supabase>=2.6
# pillow
# pillow-heif  # to support HEIC on iPhone (optional)

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

# --- Supabase client
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.warning(
        "Supabase env vars not set. Browsing will still render, but uploads won't persist.\n"
        "Set SUPABASE_URL and SUPABASE_ANON_KEY in your environment."
    )

@st.cache_resource(show_spinner=False)
def get_sb():
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

sb = get_sb()
BUCKET = "photoshare"

st.set_page_config(page_title="Photo Share (6 people)", page_icon="📸", layout="wide")

# --- Simple password gate (all 6 people share one password)
# Default password; can be overridden by env var or secrets if present
PASS = os.getenv("APP_PASS") or "eggmongol"
# Try reading from st.secrets if configured, but don't crash if not
try:
    if hasattr(st, "secrets") and isinstance(st.secrets, dict) and "APP_PASS" in st.secrets:
        PASS = st.secrets["APP_PASS"]
except Exception:
    # secrets.toml not configured; ignore
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


# --- Sidebar: simple identity
st.sidebar.header("👤 Who are you?")
user = st.sidebar.text_input("Your name (e.g., Jiho)", max_chars=24).strip()
if not user:
    st.sidebar.info("Type your name so your uploads are grouped correctly.")

# --- Tabs
tab_upload, tab_browse = st.tabs(["Upload", "Browse & Download"]) 

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

        st.markdown("**Or take a photo now**")
        snap = st.camera_input("Take a picture (optional)")

        if st.button("⬆️ Upload", type="primary", disabled=not (user and album and (files or snap))):
            if not sb:
                st.error("Supabase not configured. Set env vars and restart.")
            else:
                uploaded = 0
                # bundle files list including snap if present
                bundle: List[Tuple[str, bytes]] = []

                # Multiple files from gallery
                for f in files or []:
                    name = f.name
                    try:
                        data = f.read()
                    except Exception:
                        data = f.getvalue()
                    # Ensure orientation-correct JPEG for HEIC / others
                    try:
                        img = Image.open(io.BytesIO(data))
                        # Convert to RGB JPEG to normalize format & EXIF orientation
                        rgb = img.convert("RGB")
                        buf = io.BytesIO()
                        rgb.save(buf, format="JPEG", quality=90, optimize=True)
                        data = buf.getvalue()
                        name = os.path.splitext(name)[0] + ".jpg"
                    except Exception:
                        # If not an image we can open, keep raw
                        pass
                    bundle.append((name, data))

                # Snapshot from camera
                if snap is not None:
                    name = f"camera_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                    bundle.append((name, snap.getvalue()))

                # Upload to Supabase Storage
                with st.spinner("Uploading..."):
                    for name, data in bundle:
                        path = f"{user}/{album}/{name}"
                        try:
                            sb.storage.from_(BUCKET).upload(path, data, {
                                "contentType": "image/jpeg" if name.lower().endswith(".jpg") else "application/octet-stream",
                                "upsert": True,
                            })
                            uploaded += 1
                        except Exception as e:
                            st.error(f"Failed: {name} — {e}")
                st.success(f"Uploaded {uploaded} file(s) to {user}/{album}")

    with colB:
        st.subheader("What others will see")
        st.caption("Below is how your album appears to everyone")
        if sb and user and album:
            # List objects in this album
            prefix = f"{user}/{album}/"
            try:
                objs = sb.storage.from_(BUCKET).list(prefix)
            except Exception:
                objs = []
            thumbs = []
            for o in objs:
                if o["name"].startswith("."):
                    continue
                rel = prefix + o["name"]
                public_url = sb.storage.from_(BUCKET).get_public_url(rel)
                thumbs.append(public_url)

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
    if not sb:
        st.warning("Supabase not configured; cannot list albums.")
    else:
        # list all top-level users (folders)
        users = [o["name"] for o in sb.storage.from_(BUCKET).list("") if o.get("id") is None and o.get("name")]  # folders
        if not users:
            st.info("No uploads yet. Albums will appear here.")
        else:
            u = st.selectbox("Select a person", options=users)
            albums = [o["name"] for o in sb.storage.from_(BUCKET).list(f"{u}/") if o.get("id") is None and o.get("name")] 
            if albums:
                a = st.selectbox("Select an album", options=albums)
                prefix = f"{u}/{a}/"
                files = sb.storage.from_(BUCKET).list(prefix)
                cols = st.columns(4)
                images = []
                for i, fobj in enumerate(files):
                    if fobj.get("id") is None:  # folder
                        continue
                    rel = prefix + fobj["name"]
                    url = sb.storage.from_(BUCKET).get_public_url(rel)
                    images.append((fobj["name"], url, rel))
                    cols[i % 4].image(url, caption=fobj["name"], use_container_width=True)

                # Download ZIP of this album
                if images:
                    if st.button("⬇️ Download this album as ZIP"):
                        zip_buf = io.BytesIO()
                        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                            for fname, url, rel in images:
                                # fetch bytes from storage (signed URL download)
                                try:
                                    data = sb.storage.from_(BUCKET).download(rel)
                                    zf.writestr(fname, data)
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
st.caption("Privacy tip: this demo uses a public bucket for simplicity. For private sharing, switch to signed URLs and add passcodes.")
