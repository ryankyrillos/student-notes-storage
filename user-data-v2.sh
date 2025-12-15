#!/bin/bash
yum update -y
yum install python3 python3-pip git mysql -y

cd /home/ec2-user
# S3_BUCKET is injected via launch template or we hardcode it if known
export S3_BUCKET="student-notes-eun-472796"

# Clone repo for initial structure/dependencies
git clone https://github.com/ryankyrillos/student-notes-storage.git app
cd app

pip3 install -r requirements.txt
pip3 install gunicorn
pip3 install boto3

# OVERWRITE app.py with the patched version from S3
aws s3 cp s3://$S3_BUCKET/app.py app.py

# Environtment Variables
export RDS_HOST="student-notes-db.cnsa2ce06oai.eu-north-1.rds.amazonaws.com"
export RDS_USER="admin"
export RDS_PASSWORD="YourSecurePassword123!"
export RDS_DB="studentnotes"
export S3_BUCKET="$S3_BUCKET"
# FIXED SECRET KEY for Session Stickiness
export FLASK_SECRET_KEY="fixed-secret-key-for-student-notes-app"

# Service Setup
cat > /etc/systemd/system/studentnotes.service <<SVCEOF
[Unit]
Description=Student Notes Flask App
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/app
Environment="RDS_HOST=$RDS_HOST"
Environment="RDS_USER=$RDS_USER"
Environment="RDS_PASSWORD=$RDS_PASSWORD"
Environment="RDS_DB=$RDS_DB"
Environment="S3_BUCKET=$S3_BUCKET"
Environment="FLASK_SECRET_KEY=$FLASK_SECRET_KEY"
ExecStart=/usr/local/bin/gunicorn -w 4 -b 0.0.0.0:8080 app:app
Restart=always

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable studentnotes
systemctl start studentnotes
