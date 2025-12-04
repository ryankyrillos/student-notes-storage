# app.py
"""Flask application for Student Notes Storage System.
Features:
- User registration & login (password hashing with werkzeug.security)
- File upload to S3
- Dashboard showing uploaded notes (metadata from RDS)
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, stream_with_context, jsonify
import boto3
import pymysql
import os
from werkzeug.security import generate_password_hash, check_password_hash
import mimetypes
from botocore.exceptions import ClientError

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'super-secret-key')

# AWS clients (credentials via IAM role on EC2)
s3 = boto3.client('s3')

# RDS connection (use env vars for host, user, password, db)
conn = pymysql.connect(
    host=os.getenv('RDS_HOST'),
    user=os.getenv('RDS_USER'),
    password=os.getenv('RDS_PASSWORD'),
    database=os.getenv('RDS_DB'),
    cursorclass=pymysql.cursors.DictCursor
)

BUCKET_NAME = os.getenv('S3_BUCKET')

# ---------- Helper Functions ----------
def get_user_by_email(email):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        return cur.fetchone()

def create_user(email, password):
    pwd_hash = generate_password_hash(password)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO users (email, password_hash) VALUES (%s, %s)", (email, pwd_hash))
    conn.commit()

def get_user_files(user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE user_id=%s ORDER BY uploaded_at DESC", (user_id,))
        return cur.fetchall()

def save_file_record(user_id, filename, s3_key):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO notes (user_id, filename, s3_key) VALUES (%s, %s, %s)",
            (user_id, filename, s3_key)
        )
    conn.commit()

def delete_file_record(file_id, user_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM notes WHERE id=%s AND user_id=%s", (file_id, user_id))
    conn.commit()

def get_text_notes(user_id):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM text_notes WHERE user_id=%s ORDER BY updated_at DESC",
            (user_id,)
        )
        return cur.fetchall()

def save_text_note(user_id, title, content):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO text_notes (user_id, title, content) VALUES (%s, %s, %s)",
            (user_id, title, content)
        )
    conn.commit()

def delete_text_note(note_id, user_id):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM text_notes WHERE id=%s AND user_id=%s", (note_id, user_id))
    conn.commit()

def stream_s3_file(bucket, key, download_name):
    """Stream S3 object through Flask so browsers keep the original filename."""
    s3_object = s3.get_object(Bucket=bucket, Key=key)
    body = s3_object['Body']
    guessed_type, _ = mimetypes.guess_type(download_name)
    content_type = s3_object.get('ContentType') or guessed_type or 'application/octet-stream'

    def generate():
        chunk = body.read(8192)
        while chunk:
            yield chunk
            chunk = body.read(8192)

    response = Response(stream_with_context(generate()), mimetype=content_type)
    response.headers['Content-Disposition'] = f'attachment; filename="{download_name}"'
    content_length = s3_object.get('ContentLength')
    if content_length:
        response.headers['Content-Length'] = str(content_length)
    return response


def is_fetch_request():
    requested_with = request.headers.get('X-Requested-With', '').lower()
    return requested_with in {'xmlhttprequest', 'fetch'}


def render_dashboard_partials(files, notes):
    files_html = render_template('partials/files_list.html', files=files)
    notes_html = render_template('partials/notes_list.html', notes=notes)
    return files_html, notes_html


def dashboard_action_response(message=None, success=True, status_code=None):
    if status_code is None:
        status_code = 200 if success else 400
    if is_fetch_request():
        files = get_user_files(session['user_id'])
        notes = get_text_notes(session['user_id'])
        files_html, notes_html = render_dashboard_partials(files, notes)
        payload = {
            'status': 'ok' if success else 'error',
            'message': message,
            'files_html': files_html,
            'notes_html': notes_html
        }
        return jsonify(payload), status_code
    if message:
        flash(message)
    return redirect(url_for('dashboard'))

# ---------- Routes ----------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if get_user_by_email(email):
            flash('Email already registered')
            return redirect(url_for('register'))
        create_user(email, password)
        flash('Registration successful, please log in')
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']
    user = get_user_by_email(email)
    if user and check_password_hash(user['password_hash'], password):
        session['user_id'] = user['id']
        session['email'] = user['email']
        return redirect(url_for('dashboard'))
    flash('Invalid credentials')
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    files = get_user_files(session['user_id'])
    notes = get_text_notes(session['user_id'])
    return render_template('dashboard.html', files=files, notes=notes)

@app.route('/upload', methods=['POST'])
def upload():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    uploaded_file = request.files.get('file')
    if not uploaded_file or uploaded_file.filename == '':
        return dashboard_action_response('Please choose a file to upload', success=False)
    s3_key = f"{session['user_id']}/{uploaded_file.filename}"
    try:
        s3.upload_fileobj(uploaded_file, BUCKET_NAME, s3_key)
    except Exception:
        return dashboard_action_response('Unable to upload file right now', success=False, status_code=502)
    save_file_record(session['user_id'], uploaded_file.filename, s3_key)
    return dashboard_action_response('File uploaded successfully')

@app.route('/download/<int:file_id>')
def download(file_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    # Get file record and verify ownership
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE id=%s AND user_id=%s", (file_id, session['user_id']))
        file_record = cur.fetchone()
    if not file_record:
        flash('File not found')
        return redirect(url_for('dashboard'))
    try:
        return stream_s3_file(BUCKET_NAME, file_record['s3_key'], file_record['filename'])
    except ClientError:
        flash('File is missing from storage')
    except Exception:
        flash('Unable to download file right now')
    return redirect(url_for('dashboard'))

@app.route('/files/<int:file_id>/delete', methods=['POST'])
def delete_file(file_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE id=%s AND user_id=%s", (file_id, session['user_id']))
        file_record = cur.fetchone()
    if not file_record:
        return dashboard_action_response('File not found', success=False, status_code=404)
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=file_record['s3_key'])
    except Exception:
        return dashboard_action_response('Unable to remove file from storage; try again later', success=False, status_code=502)
    delete_file_record(file_id, session['user_id'])
    return dashboard_action_response('File deleted successfully')

@app.route('/notes', methods=['POST'])
def create_note():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    title = request.form.get('note_title', '').strip() or 'Untitled note'
    content = request.form.get('note_content', '').strip()
    if not content:
        return dashboard_action_response('Note content cannot be empty', success=False)
    save_text_note(session['user_id'], title, content)
    return dashboard_action_response('Note saved successfully')

@app.route('/notes/<int:note_id>/delete', methods=['POST'])
def remove_note(note_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM text_notes WHERE id=%s AND user_id=%s",
            (note_id, session['user_id'])
        )
        note = cur.fetchone()
    if not note:
        return dashboard_action_response('Note not found', success=False, status_code=404)
    delete_text_note(note_id, session['user_id'])
    return dashboard_action_response('Note deleted')

if __name__ == '__main__':
    # In production use gunicorn; this block is for local testing
    app.run(host='0.0.0.0', port=8080, debug=False)
