from flask import Flask, request, send_file
import zipfile
import traceback
import os
from PIL import Image
import shutil
import uuid
from flask_cors import CORS
import io

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
CORS(app, origins=["*", "null"])

SCALE_FACTOR = 4


@app.post("/upscale")
def upscale_zip():
    if "file" not in request.files:
        return {"error": "No file uploaded"}, 400

    uploaded_zip = request.files["file"]

    # Temporary directory
    session_id = str(uuid.uuid4())
    temp_dir = os.path.join("temp", session_id)
    input_dir = os.path.join(temp_dir, "input")

    os.makedirs(input_dir, exist_ok=True)

    # Save uploaded zip
    zip_path = os.path.join(temp_dir, "uploaded.zip")
    uploaded_zip.save(zip_path)

    # Extract zip
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(input_dir)

    # Create an in-memory ZIP buffer
    mem_zip = io.BytesIO()

    # Write upscaled images to memory ZIP
    with zipfile.ZipFile(mem_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in os.listdir(input_dir):
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):

                img = Image.open(os.path.join(input_dir, f)).convert("RGB")
                new_w = img.width * SCALE_FACTOR
                new_h = img.height * SCALE_FACTOR
                upscaled = img.resize((new_w, new_h), Image.LANCZOS)

                # save image to memory buffer before writing
                img_bytes = io.BytesIO()
                upscaled.save(img_bytes, format="JPEG", quality=95)
                img_bytes.seek(0)

                # Safe filename
                safe_name = f"image_{uuid.uuid4().hex}.jpg"
                zf.writestr(safe_name, img_bytes.read())

    mem_zip.seek(0)

    # Cleanup temp folder on disk
    shutil.rmtree(temp_dir)

    # Send ZIP created in memory
    return send_file(
        mem_zip,
        as_attachment=True,
        download_name="upscaled_images.zip",
        mimetype="application/zip"
    )


@app.errorhandler(Exception)
def handle_error(e):
    print("\n===== BACKEND ERROR =====")
    traceback.print_exc()
    print("===== END ERROR =====\n")
    return {"error": str(e)}, 500


if __name__ == "__main__":
    os.makedirs("temp", exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
