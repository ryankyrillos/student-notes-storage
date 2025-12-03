# Student Notes Storage System

A secure, scalable cloud-based application for students to upload, store, and access their notes.

## Features
- User registration and authentication
- Secure file upload to AWS S3 with presigned downloads
- Dashboard controls to delete uploaded files
- Browser-based text notes editor saved into MySQL
- RDS MySQL database for user and note data
- Auto-scaling EC2 infrastructure
- CloudWatch monitoring

## Architecture
- **Frontend**: Flask templates with modern CSS
- **Backend**: Python Flask
- **Storage**: AWS S3 (encrypted)
- **Database**: AWS RDS MySQL
- **Hosting**: EC2 with Auto Scaling Group
- **Load Balancing**: Application Load Balancer
- **Monitoring**: CloudWatch

## Environment Variables
Create a `.env` file with:
```
RDS_HOST=your-rds-endpoint
RDS_USER=admin
RDS_PASSWORD=your-password
RDS_DB=studentnotes
S3_BUCKET=your-bucket-name
FLASK_SECRET_KEY=your-secret-key
```

## Installation
```bash
pip install -r requirements.txt
python app.py
```

## AWS Project - December 2025
Developed as part of Cloud Computing course project.
