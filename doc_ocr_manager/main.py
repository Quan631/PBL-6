# app.py
from __future__ import annotations

import os
from pathlib import Path
import streamlit as st

def st_image(col, image, caption=None):
    try:
        col.image(image, caption=caption, use_container_width=True)
    except TypeError:
        # Streamlit cũ: dùng use_column_width
        col.image(image, caption=caption, use_column_width=True)


from core.db import (
    get_conn, init_db, upsert_document, insert_image, update_image_ocr,
    get_documents, get_document, get_images_by_doc,
    search_documents, search_images, stats_count_by_type
)
from core.storage import (
    ensure_dirs, doc_upload_dir, doc_export_dir,
    new_doc_id, safe_filename, now_iso
)
from core.ocr_engine import run_easyocr
from core.classifier import classify_document
from core.exporters import export_to_word, export_to_excel


BASE_DIR = Path(__file__).parent
DATA_DIR, UPLOADS_DIR, EXPORTS_DIR = ensure_dirs(BASE_DIR)
DB_PATH = DATA_DIR / "app.db"


@st.cache_resource
def get_ocr_reader():
    # EasyOCR supports Vietnamese + English
    import easyocr
    return easyocr.Reader(["vi", "en"], gpu=False)


def file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def page_upload(conn):
    st.header("📤 Upload Images → OCR → Export Word/Excel")

    with st.form("upload_form", clear_on_submit=False):
        title = st.text_input("Document title", value="")
        enhance = st.checkbox("Enhance image before OCR (recommended)", value=True)
        run_now = st.checkbox("Run OCR now", value=True)
        files = st.file_uploader(
            "Upload images (PNG/JPG/JPEG) - multiple allowed",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        submitted = st.form_submit_button("Create Document")

    if not submitted:
        return

    if not files:
        st.error("Please upload at least 1 image.")
        return

    doc_id = new_doc_id()
    created_at = now_iso()
    upload_dir = doc_upload_dir(UPLOADS_DIR, doc_id)
    export_dir = doc_export_dir(EXPORTS_DIR, doc_id)

    # Save images first
    saved_images = []
    for f in files:
        fn = safe_filename(f.name)
        out_path = upload_dir / fn
        out_path.write_bytes(f.getbuffer())
        insert_image(conn, doc_id, fn, str(out_path), ocr_text=None)
        saved_images.append({"filename": fn, "stored_path": out_path, "ocr_text": ""})

    st.success(f"Saved {len(saved_images)} images. Document ID = {doc_id}")

    # OCR
    combined_text = ""
    if run_now:
        reader = get_ocr_reader()
        prog = st.progress(0)
        for i, img in enumerate(saved_images, start=1):
            try:
                text, conf = run_easyocr(reader, str(img["stored_path"]), enhance=enhance)
            except Exception as e:
                text = ""
                conf = 0.0
                st.warning(f"OCR failed for {img['filename']}: {e}")

            img["ocr_text"] = text
            update_image_ocr(conn, doc_id, str(img["stored_path"]), text)

            if text:
                combined_text += f"\n\n--- {img['filename']} ---\n{text}"

            prog.progress(int(i / len(saved_images) * 100))

        prog.empty()
        st.success("OCR completed!")

    # Classify
    doc_type = classify_document(combined_text)

    # Export
    word_path = export_dir / f"{doc_id}.docx"
    excel_path = export_dir / f"{doc_id}.xlsx"

    try:
        export_to_word(
            out_path=word_path,
            title=title or f"Document {doc_id}",
            doc_id=doc_id,
            doc_type=doc_type,
            created_at=created_at,
            images=saved_images,
        )
        export_to_excel(
            out_path=excel_path,
            doc_id=doc_id,
            doc_type=doc_type,
            created_at=created_at,
            images=saved_images,
        )
    except Exception as e:
        st.error(f"Export failed: {e}")
        word_path = None
        excel_path = None

    # Save doc in DB
    upsert_document(conn, {
        "id": doc_id,
        "title": title or f"Document {doc_id}",
        "created_at": created_at,
        "doc_type": doc_type,
        "ocr_text": combined_text,
        "word_path": str(word_path) if word_path else None,
        "excel_path": str(excel_path) if excel_path else None,
    })

    st.subheader("✅ Result")
    cols = st.columns(3)
    cols[0].metric("Doc ID", doc_id)
    cols[1].metric("Type", doc_type)
    cols[2].metric("Images", len(saved_images))

    st.write("Preview thumbnails:")
    thumbs = st.columns(min(4, len(saved_images)))
    for i, img in enumerate(saved_images[:8]):
        thumbs[i % len(thumbs)].image(str(img["stored_path"]), caption=img["filename"], use_container_width=True)

    if word_path and word_path.exists():
        st.download_button(
            "⬇️ Download Word (.docx)",
            data=file_bytes(word_path),
            file_name=word_path.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    if excel_path and excel_path.exists():
        st.download_button(
            "⬇️ Download Excel (.xlsx)",
            data=file_bytes(excel_path),
            file_name=excel_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    with st.expander("OCR Text (combined)", expanded=False):
        st.text_area("OCR", combined_text, height=240)


def page_library(conn):
    st.header("📚 Library")
    doc_type = st.selectbox("Filter by type", ["All", "Invoice", "Government Telegram", "Normal"])
    docs = get_documents(conn, doc_type=doc_type, limit=200)

    if not docs:
        st.info("No documents yet. Go to Upload.")
        return

    # Picker
    options = [f"{d['id']} | {d['doc_type']} | {d['title']}" for d in docs]
    pick = st.selectbox("Select a document", options)
    doc_id = pick.split("|")[0].strip()

    doc = get_document(conn, doc_id)
    if not doc:
        st.error("Document not found.")
        return

    st.subheader(f"📄 {doc['title']}")
    c1, c2, c3 = st.columns(3)
    c1.write(f"**Doc ID:** {doc['id']}")
    c2.write(f"**Type:** {doc['doc_type']}")
    c3.write(f"**Created:** {doc['created_at']}")

    imgs = get_images_by_doc(conn, doc_id)
    st.write(f"**Images:** {len(imgs)}")

    # Downloads
    word_path = Path(doc["word_path"]) if doc["word_path"] else None
    excel_path = Path(doc["excel_path"]) if doc["excel_path"] else None

    dcols = st.columns(2)
    if word_path and word_path.exists():
        dcols[0].download_button(
            "⬇️ Download Word (.docx)",
            data=file_bytes(word_path),
            file_name=word_path.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    else:
        dcols[0].info("Word not available yet.")

    if excel_path and excel_path.exists():
        dcols[1].download_button(
            "⬇️ Download Excel (.xlsx)",
            data=file_bytes(excel_path),
            file_name=excel_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        dcols[1].info("Excel not available yet.")

    # Thumbnails
    st.write("Thumbnails:")
    cols = st.columns(4)
    for i, im in enumerate(imgs[:24]):
        cols[i % 4].image(im["stored_path"], caption=im["filename"], use_container_width=True)

    with st.expander("OCR Text (combined)", expanded=False):
        st.text_area("OCR", doc["ocr_text"] or "", height=280)


def page_search(conn):
    st.header("🔎 Search")

    tab1, tab2 = st.tabs(["Search Documents", "Search Images"])

    with tab1:
        q = st.text_input("Search by Doc ID / Title / OCR content (FTS supported)", value="")
        doc_type = st.selectbox("Type", ["All", "Invoice", "Government Telegram", "Normal"], key="doc_type_search")
        if st.button("Search Documents"):
            if not q.strip():
                st.warning("Enter a query.")
            else:
                res = search_documents(conn, q.strip(), doc_type=doc_type, limit=100)
                st.write(f"Found **{len(res)}** documents.")
                for d in res:
                    with st.expander(f"{d['id']} | {d['doc_type']} | {d['title']}"):
                        st.write(f"Created: {d['created_at']}")
                        word_path = Path(d["word_path"]) if d["word_path"] else None
                        excel_path = Path(d["excel_path"]) if d["excel_path"] else None
                        c1, c2 = st.columns(2)
                        if word_path and word_path.exists():
                            c1.download_button(
                                "⬇️ Word",
                                data=file_bytes(word_path),
                                file_name=word_path.name,
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            )
                        if excel_path and excel_path.exists():
                            c2.download_button(
                                "⬇️ Excel",
                                data=file_bytes(excel_path),
                                file_name=excel_path.name,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        imgs = get_images_by_doc(conn, d["id"])
                        cols = st.columns(min(4, max(1, len(imgs))))
                        for i, im in enumerate(imgs[:8]):
                            cols[i % len(cols)].image(im["stored_path"], caption=im["filename"], use_container_width=True)

    with tab2:
        q2 = st.text_input("Search images by filename or OCR text", value="")
        if st.button("Search Images"):
            if not q2.strip():
                st.warning("Enter a query.")
            else:
                res = search_images(conn, q2.strip(), limit=200)
                st.write(f"Found **{len(res)}** images.")
                cols = st.columns(4)
                for i, im in enumerate(res[:40]):
                    cols[i % 4].image(im["stored_path"], caption=f"{im['filename']} (doc: {im['document_id']})", use_container_width=True)


def page_stats(conn):
    st.header("📊 Statistics")
    stats = stats_count_by_type(conn)
    if not stats:
        st.info("No data yet.")
        return

    total = sum(cnt for _, cnt in stats)
    st.metric("Total documents", total)

    # show metrics
    mcols = st.columns(min(3, len(stats)))
    for i, (t, cnt) in enumerate(stats[:3]):
        mcols[i].metric(t, cnt)

    # chart
    import pandas as pd
    df = pd.DataFrame(stats, columns=["doc_type", "count"])
    st.bar_chart(df.set_index("doc_type"))


def page_settings(conn):
    st.header("⚙️ Settings / Maintenance")
    st.write(f"Data folder: `{DATA_DIR}`")
    st.write(f"DB path: `{DB_PATH}`")

    st.warning("Danger zone (reset)")

    if st.button("Reset database (keep files)"):
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS images")
        cur.execute("DROP TABLE IF EXISTS documents")
        try:
            cur.execute("DROP TABLE IF EXISTS documents_fts")
        except Exception:
            pass
        conn.commit()
        init_db(conn)
        st.success("Database reset completed.")

    if st.button("Delete ALL data (DB + files)"):
        try:
            conn.close()
        except Exception:
            pass

        import shutil
        try:
            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR)
        except Exception as e:
            st.error(f"Failed to delete data dir: {e}")
            return

        st.success("Deleted all data. Please restart the app.")


def main():
    st.set_page_config(page_title="Document OCR Manager", layout="wide")
    st.title("🧾 Document OCR Manager (VI + EN)")

    conn = get_conn(DB_PATH)
    init_db(conn)

    page = st.sidebar.radio(
        "Navigation",
        ["Upload", "Library", "Search", "Stats", "Settings"],
        index=0
    )

    if page == "Upload":
        page_upload(conn)
    elif page == "Library":
        page_library(conn)
    elif page == "Search":
        page_search(conn)
    elif page == "Stats":
        page_stats(conn)
    else:
        page_settings(conn)


if __name__ == "__main__":
    main()
