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

# Allow partial and large images in streaming mode
ImageFile.LOAD_TRUNCATED_IMAGES = True

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB upload max
CORS(app, resources={r"/*": {"origins": ["*", "null"]}})

SCALE_FACTOR = 4
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}


def is_image_filename(name: str) -> bool:
    _, ext = os.path.splitext(name.lower())
    return ext in ALLOWED_EXT


@app.get("/")
def index():
    return jsonify({"status": "ok", "note": "Upscale API running"})


@app.post("/upscale")
def upscale_zip():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        uploaded = request.files["file"]

        # Temporary directory for this request
        temp_root = tempfile.mkdtemp(prefix="upscale_")
        input_dir = os.path.join(temp_root, "input")
        output_dir = os.path.join(temp_root, "output")
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # Save uploaded ZIP
        uploaded_zip_path = os.path.join(temp_root, "uploaded.zip")
        uploaded.save(uploaded_zip_path)

        # Extract uploaded ZIP safely
        with zipfile.ZipFile(uploaded_zip_path, "r") as z:
            for member in z.namelist():
                if member.endswith("/"):
                    continue
                filename = os.path.basename(member)
                if not filename:
                    continue
                dest = os.path.join(input_dir, filename)
                with z.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        # Process images STREAMING one-by-one
        for fname in os.listdir(input_dir):
            if not is_image_filename(fname):
                continue

            in_path = os.path.join(input_dir, fname)

            try:
                with Image.open(in_path) as img:
                    img = img.convert("RGB")
                    new_w = img.width * SCALE_FACTOR
                    new_h = img.height * SCALE_FACTOR

                    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

                    safe_name = f"image_{uuid.uuid4().hex}.jpg"
                    out_path = os.path.join(output_dir, safe_name)
                    upscaled.save(out_path, "JPEG", quality=90)

                del upscaled
            except Exception as e:
                print(f"[WARN] Failed processing {in_path}: {e}")
            finally:
                gc.collect()

        # Create final ZIP on disk
        output_zip_path = os.path.join(temp_root, "upscaled_images.zip")
        with zipfile.ZipFile(output_zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for out_file in os.listdir(output_dir):
                zout.write(os.path.join(output_dir, out_file), arcname=out_file)

        response = send_file(output_zip_path, as_attachment=True)

        def cleanup():
            try:
                shutil.rmtree(temp_root)
            except Exception as e:
                print("Cleanup error:", e)

        response.call_on_close(cleanup)
        return response

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
