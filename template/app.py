import os
import uuid
from flask import Flask, render_template, request, redirect, flash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)

app = Flask(__name__)

app.secret_key = "bigbanggang"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB limit

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
BUCKET = "study-materials"
SUBJECTS = ["Biology", "Chemistry", "Physics", "Maths", "English", "German", "Geography", "Computer Science", "Other"]

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    subject = request.args.get("subject", "").strip()

    try:
        query = supabase.table("materials").select("*")

        if subject in SUBJECTS:
            query = query.eq("subject", subject)

        if q:
            # Remove characters that would confuse the search filter
            for ch in [",", "(", ")", "%", "*", '"']:
                q = q.replace(ch, " ")
            q = q.strip()
            if q:
                pattern = f"%{q}%"
                query = query.or_(
                    f'title.ilike."{pattern}",'
                    f'description.ilike."{pattern}",'
                    f'subject.ilike."{pattern}"'
                )

        response = query.order("created_at", desc=True).execute()
        materials = response.data
    except Exception as e:
        print("LOAD ERROR:", e)
        materials = []

    return render_template(
        "index.html",
        materials=materials,
        subjects=SUBJECTS,
        q=request.args.get("q", ""),
        selected_subject=subject,
    )

@app.route("/test")
def test():
    response = supabase.table("materials").select("*").execute()
    return f"Connected! Rows found: {len(response.data)}"

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        subject = request.form.get("subject", "").strip()
        description = request.form.get("description", "").strip()
        file = request.files.get("image")

        if not title or not file or file.filename == "":
            flash("Please enter a title and choose an image.")
            return redirect("/upload")
        if subject not in SUBJECTS:
            flash("Please choose a subject.")
            return redirect("/upload")
        if not allowed_file(file.filename):
            flash("Only png, jpg, jpeg, gif and webp images are allowed.")
            return redirect("/upload")

        # Make the filename safe and unique
        safe_name = secure_filename(file.filename)
        path = f"{uuid.uuid4().hex}_{safe_name}"

        try:
            file_bytes = file.read()
            supabase.storage.from_(BUCKET).upload(
                path, file_bytes, {"content-type": file.mimetype}
            )
            image_url = supabase.storage.from_(BUCKET).get_public_url(path)

            supabase.table("materials").insert({
                "title": title,
                "subject": subject,
                "description": description,
                "image_path": path,
                "image_url": image_url,
            }).execute()
        except Exception as e:
            print("UPLOAD ERROR:", e)
            flash("Something went wrong while uploading. Please try again.")
            return redirect("/upload")

        flash("Upload successful!")
        return redirect("/upload")

    return render_template("upload.html", subjects=SUBJECTS)
if __name__ == "__main__":
    app.run(debug=True)