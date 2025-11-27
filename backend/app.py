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
CORS(app, resources={r"/*": {
    "origins": ["*", "null"],
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": "*"
}})

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
    print("---- /upscale HIT ----")

    try:
        if "file" not in request.files:
            print("❌ ERROR: No file found in request")
            return jsonify({"error": "No file uploaded"}), 400

        uploaded = request.files["file"]
        print("Uploaded filename:", uploaded.filename)

        # Temp root directory
        temp_root = tempfile.mkdtemp(prefix="upscale_")
        print("Temp directory:", temp_root)

        input_dir = os.path.join(temp_root, "input")
        output_dir = os.path.join(temp_root, "output")
        os.makedirs(input_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        # Save ZIP to disk
        uploaded_zip_path = os.path.join(temp_root, "uploaded.zip")
        uploaded.save(uploaded_zip_path)
        print("ZIP saved at:", uploaded_zip_path)

        # Try extracting
        try:
            with zipfile.ZipFile(uploaded_zip_path, "r") as z:
                print("ZIP entries:", z.namelist())
                z.extractall(input_dir)
        except Exception as e:
            print("❌ ZIP EXTRACT ERROR:", e)
            raise

        # List extracted files
        print("Extracted files:", os.listdir(input_dir))

        # PROCESS images
        for fname in os.listdir(input_dir):
            print("Processing:", fname)
            if not is_image_filename(fname):
                print("Skipping non-image:", fname)
                continue

            img_path = os.path.join(input_dir, fname)

            try:
                with Image.open(img_path) as img:
                    print("Opened image:", fname, img.size)

                    img = img.convert("RGB")
                    new_w = img.width * SCALE_FACTOR
                    new_h = img.height * SCALE_FACTOR
                    upscaled = img.resize((new_w, new_h), Image.LANCZOS)

                    out_name = f"image_{uuid.uuid4().hex}.jpg"
                    out_path = os.path.join(output_dir, out_name)
                    upscaled.save(out_path, "JPEG", quality=90)
                    print("Saved:", out_path)

            except Exception as e:
                print("❌ IMAGE ERROR:", e)
                raise

        # Create output ZIP
        output_zip_path = os.path.join(temp_root, "upscaled_images.zip")
        with zipfile.ZipFile(output_zip_path, "w") as zout:
            for file in os.listdir(output_dir):
                zout.write(os.path.join(output_dir, file), file)

        print("ZIP ready:", output_zip_path)

        response = send_file(output_zip_path, as_attachment=True)

        def cleanup():
            print("Cleaning temp:", temp_root)
            shutil.rmtree(temp_root)

        response.call_on_close(cleanup)
        return response

    except Exception as e:
        print("\n❌ GLOBAL ERROR:", e)
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
