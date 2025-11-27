import os
import zipfile
import traceback
import tempfile
import shutil
import uuid
import gc
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from PIL import Image, ImageFile

# Allow loading potentially large images in a streaming manner
ImageFile.LOAD_TRUNCATED_IMAGES = True
# Optionally increase maximum allowed pixels to avoid PIL DecompressionBombError for large upscales.
# Only change if you understand memory implications.
# Image.MAX_IMAGE_PIXELS = 1000000000

app = Flask(__name__)

# Production-ish settings
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB upload max (adjust if needed)

# Allow file:// (origin null) for local testing and all origins for deployed frontend.
CORS(app, origins=["*", "null"])

# Upscale factor (adjustable)
SCALE_FACTOR = int(os.environ.get("SCALE_FACTOR", "4"))

# Allowed image extensions
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def is_image_filename(name: str) -> bool:
    _, ext = os.path.splitext(name.lower())
    return ext in ALLOWED_EXT


@app.post("/upscale")
def upscale_zip():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        uploaded = request.files["file"]

        # create a unique temporary directory for this request
        temp_root = tempfile.mkdtemp(prefix="upscale_")
        input_dir = os.path.join(temp_root, "input")
        output_dir = os.path.join(temp_root, "output")
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # Save the uploaded ZIP to disk (not in memory)
        uploaded_zip_path = os.path.join(temp_root, "uploaded.zip")
        uploaded.save(uploaded_zip_path)

        # Extract uploaded zip to input_dir
        with zipfile.ZipFile(uploaded_zip_path, "r") as z:
            # Extract only files (skip directories) safely
            for member in z.namelist():
                # skip directory entries
                if member.endswith("/"):
                    continue
                # sanitize name: take basename to avoid path traversal inside zip
                filename = os.path.basename(member)
                if not filename:
                    continue
                dest = os.path.join(input_dir, filename)
                with z.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # Process files one by one - upscale and save into output_dir with safe names
        for fname in os.listdir(input_dir):
            if not is_image_filename(fname):
                # skip non-image files (optional: copy them unchanged if you want)
                continue

            in_path = os.path.join(input_dir, fname)

            # Open, convert, resize, save - all in a small scope so memory is freed promptly
            try:
                with Image.open(in_path) as img:
                    # Convert to RGB to remove metadata and ensure consistent encoding
                    img = img.convert("RGB")
                    new_w = img.width * SCALE_FACTOR
                    new_h = img.height * SCALE_FACTOR

                    # Resize using LANCZOS (high-quality)
                    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

                    # Safe output filename
                    safe_name = f"image_{uuid.uuid4().hex}.jpg"
                    out_path = os.path.join(output_dir, safe_name)

                    # Save to disk in JPEG (reasonable size) - adjust quality as needed
                    upscaled.save(out_path, format="JPEG", quality=90)
                    # Explicitly delete PIL objects to free memory
                    del upscaled
            except Exception as e:
                # Log error but continue processing other files
                print(f"[WARN] Failed to process {in_path}: {e}")
                traceback.print_exc()
            finally:
                # ensure garbage collection runs to free memory between iterations
                gc.collect()

        # Create the final ZIP on disk streaming files into it (low memory)
        output_zip_path = os.path.join(temp_root, "upscaled_images.zip")
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for out_fname in os.listdir(output_dir):
                out_full = os.path.join(output_dir, out_fname)
                # add file with arcname equal to filename only (no directories)
                zout.write(out_full, arcname=out_fname)

        # Prepare response - send_file will stream file to client
        # To ensure safe cleanup, schedule temp removal after the response finishes
        response = send_file(
            output_zip_path,
            as_attachment=True,
            download_name="upscaled_images.zip",
            mimetype="application/zip",
            conditional=True,
        )

        def cleanup():
            try:
                shutil.rmtree(temp_root)
                print("[CLEANUP] removed temp:", temp_root)
            except Exception as e:
                print("[CLEANUP ERROR]", e)

        # call_on_close is safe cross-platform for cleaning after streaming completes
        response.call_on_close(cleanup)
        return response

    except Exception as e:
        print("\n===== BACKEND ERROR =====")
        traceback.print_exc()
        print("===== END =====\n")
        # try best-effort cleanup
        try:
            if "temp_root" in locals() and os.path.exists(temp_root):
                shutil.rmtree(temp_root)
        except Exception:
            pass
        return jsonify({"error": str(e)}), 500


@app.get("/")
def index():
    return jsonify({"status": "ok", "note": "Upscale API running"})


if __name__ == "__main__":
    # Ensure temp folder parent exists (tempfile.mkdtemp will create per-call dir anyway)
    os.makedirs("temp", exist_ok=True)
    # Use port supplied by Render; allow binding to all interfaces
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
