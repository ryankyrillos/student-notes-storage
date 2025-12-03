# app.py
"""Flask application for Student Notes Storage System.
Features:
- User registration & login (password hashing with werkzeug.security)
- File upload to S3
- Dashboard showing uploaded notes (metadata from RDS)
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash
import boto3
import pymysql
import os
from werkzeug.security import generate_password_hash, check_password_hash

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
    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        flash('No file selected')
        return redirect(url_for('dashboard'))
    # Generate a unique S3 key
    s3_key = f"{session['user_id']}/{uploaded_file.filename}"
    s3.upload_fileobj(uploaded_file, BUCKET_NAME, s3_key)
    save_file_record(session['user_id'], uploaded_file.filename, s3_key)
    flash('File uploaded successfully')
    return redirect(url_for('dashboard'))

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
    # Generate presigned URL (valid for 1 hour)
    presigned_url = s3.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': BUCKET_NAME,
            'Key': file_record['s3_key'],
            'ResponseContentDisposition': f"attachment; filename=\"{file_record['filename']}\""
        },
        ExpiresIn=3600
    )
    return redirect(presigned_url)

@app.route('/files/<int:file_id>/delete', methods=['POST'])
def delete_file(file_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM notes WHERE id=%s AND user_id=%s", (file_id, session['user_id']))
        file_record = cur.fetchone()
    if not file_record:
        flash('File not found')
        return redirect(url_for('dashboard'))
    try:
        s3.delete_object(Bucket=BUCKET_NAME, Key=file_record['s3_key'])
    except Exception:
        flash('Unable to remove file from storage; try again later')
        return redirect(url_for('dashboard'))
    delete_file_record(file_id, session['user_id'])
    flash('File deleted successfully')
    return redirect(url_for('dashboard'))

@app.route('/notes', methods=['POST'])
def create_note():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    title = request.form.get('note_title', '').strip() or 'Untitled note'
    content = request.form.get('note_content', '').strip()
    if not content:
        flash('Note content cannot be empty')
        return redirect(url_for('dashboard'))
    save_text_note(session['user_id'], title, content)
    flash('Note saved successfully')
    return redirect(url_for('dashboard'))

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
        flash('Note not found')
        return redirect(url_for('dashboard'))
    delete_text_note(note_id, session['user_id'])
    flash('Note deleted')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    # In production use gunicorn; this block is for local testing
    app.run(host='0.0.0.0', port=8080, debug=False)
