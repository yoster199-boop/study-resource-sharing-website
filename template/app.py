import os
import uuid
import re
from flask import Flask, render_template, request, redirect, flash, session, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from supabase import create_client


load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")
supabase = create_client(url, key)
auth_client = create_client(url, key)

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB limit

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
BUCKET = "study-materials"
SUBJECTS = ["Biology", "Chemistry", "Physics", "Maths", "English", "German", "Geography", "Computer Science", "Other"]

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
def logged_in():
    return "user_id" in session

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    subject = request.args.get("subject", "").strip()

    try:
        query = supabase.table("materials").select("*, profiles(username)")

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
    if not logged_in():
        flash("Please log in to upload.")
        return redirect("/login")
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
                "user_id": session["user_id"],
            }).execute()
        except Exception as e:
            print("UPLOAD ERROR:", e)
            flash("Something went wrong while uploading. Please try again.")
            return redirect("/upload")

        flash("Upload successful!")
        return redirect("/upload")

    return render_template("upload.html", subjects=SUBJECTS)
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not email or len(password) < 8:
            flash("Enter an email and a password of at least 8 characters.")
            return redirect("/signup")
        if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
            flash("Username must be 3-20 characters: letters, numbers, underscores.")
            return redirect("/signup")
        
        taken = supabase.table("profiles").select("user_id").eq("username", username).execute()
        if taken.data:
            flash("That username is taken.")
            return redirect("/signup")
        
        try:
            result = auth_client.auth.sign_up({"email": email, "password": password})
            if result.user is None:
                raise Exception("No user returned")
            supabase.table("profiles").insert({
            "user_id": result.user.id,
            "username": username,
}).execute()
        except Exception as e:
            print("SIGNUP ERROR:", e)
            flash("Could not create account. The email may already be in use.")
            return redirect("/signup")

        flash("Account created! Please log in.")
        return redirect("/login")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        try:
            result = auth_client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            session["user_id"] = result.user.id
            session["email"] = result.user.email
            prof = supabase.table("profiles").select("username").eq("user_id", result.user.id).execute()
            session["username"] = prof.data[0]["username"] if prof.data else None
        except Exception as e:
            print("LOGIN ERROR:", e)
            flash("Incorrect email or password.")
            return redirect("/login")

        flash("Logged in!")
        return redirect("/")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.")
    return redirect("/")

@app.route("/my-uploads")
def my_uploads():
    if not logged_in():
        flash("Please log in to see your uploads.")
        return redirect("/login")

    try:
        response = (
            supabase.table("materials")
            .select("*")
            .eq("user_id", session["user_id"])
            .order("created_at", desc=True)
            .execute()
        )
        materials = response.data
    except Exception as e:
        print("MY UPLOADS ERROR:", e)
        materials = []

    return render_template("my_uploads.html", materials=materials)

@app.route("/delete/<int:item_id>", methods=["POST"])
def delete(item_id):
    if not logged_in():
        flash("Please log in.")
        return redirect("/login")

    try:
        # Find the row, but only if it belongs to this user
        result = (
            supabase.table("materials")
            .select("*")
            .eq("id", item_id)
            .eq("user_id", session["user_id"])
            .execute()
        )

        if not result.data:
            flash("Item not found, or it isn't yours.")
            return redirect("/my-uploads")

        item = result.data[0]

        # Delete the file from Storage, then the row from the table
        supabase.storage.from_(BUCKET).remove([item["image_path"]])
        supabase.table("materials").delete().eq("id", item_id).eq(
            "user_id", session["user_id"]
        ).execute()

    except Exception as e:
        print("DELETE ERROR:", e)
        flash("Something went wrong while deleting.")
        return redirect("/my-uploads")

    flash("Deleted.")
    return redirect("/my-uploads")

@app.route("/u/<username>")
def profile(username):
    try:
        prof = supabase.table("profiles").select("*").eq("username", username.lower()).execute()
        if not prof.data:
            return "User not found", 404
        profile_data = prof.data[0]

        notes = (
            supabase.table("materials")
            .select("*")
            .eq("user_id", profile_data["user_id"])
            .order("created_at", desc=True)
            .execute()
        ).data
    except Exception as e:
        print("PROFILE ERROR:", e)
        return "Something went wrong", 500

    is_owner = session.get("user_id") == profile_data["user_id"]
    return render_template("profile.html", profile=profile_data, notes=notes, is_owner=is_owner)


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if not logged_in():
        flash("Please log in.")
        return redirect("/login")

    if request.method == "POST":
        bio = request.form.get("bio", "").strip()[:300]
        try:
            supabase.table("profiles").update({"bio": bio}).eq("user_id", session["user_id"]).execute()
        except Exception as e:
            print("SETTINGS ERROR:", e)
            flash("Could not save.")
            return redirect("/settings")
        flash("Profile updated.")
        return redirect(f"/u/{session['username']}")

    prof = supabase.table("profiles").select("*").eq("user_id", session["user_id"]).execute()
    return render_template("settings.html", profile=prof.data[0])

if __name__ == "__main__":
    app.run(debug=True)